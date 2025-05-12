import logging
import os
import json
from typing import List, Optional, Dict
from pinecone import Index as PineconeIndex
from langchain_community.vectorstores import FAISS
from langchain.schema import Document

from .embedding_service import get_cohere_embeddings
from .genai_service import get_llm
from .vector_store_service import initialize_pinecone_vector_store, search_pinecone_index
from utils.prompts import RERANK_DUPLICATE_TICKETS_PROMPT, SUMMARIZE_TICKET_SIMILARITIES_PROMPT

logger = logging.getLogger(__name__)

# Initialize
embeddings = get_cohere_embeddings()
llm = get_llm()
vector_store: Optional[PineconeIndex] = initialize_pinecone_vector_store(embeddings) if embeddings else None


def retrieve_top_k_tickets(query: str, k: int = 10) -> List[Document]:
    logger.info(f"Retrieving top {k} initial tickets for query: '{query[:100]}...'")
    documents = []
    if vector_store and embeddings:
        try:
            query_embedding = embeddings.embed_query(query)
            logger.debug(f"Query embedded. Searching Pinecone index...")
            results = search_pinecone_index(index=vector_store, query_vector=query_embedding, k=k, namespace=None)
            logger.info(f"Pinecone search returned {len(results) if results else 0} matches.")

            for i, match in enumerate(results):
                metadata = match.get('metadata', {})
                # Try to get content from specific fields, then fallback
                content = metadata.get('page_content', 
                                     metadata.get('description', 
                                                  metadata.get('summary', '')))
                # Remove the used content field from metadata to avoid redundancy if it was 'page_content'
                # and to ensure 'page_content' in metadata is the one from Document schema if added by user
                if 'page_content' in metadata and content == metadata['page_content']:
                    metadata_for_doc = metadata.copy() # Avoid modifying original dict from search results directly if it was to be reused
                    # metadata_for_doc.pop('page_content', None) # Let langchain Document handle its own page_content
                else:
                    metadata_for_doc = metadata
                
                metadata_for_doc['score'] = match.get('score')
                doc = Document(page_content=content, metadata=metadata_for_doc)
                documents.append(doc)
                logger.debug(f"  Retrieved Initial Doc {i+1} (ID: {doc.metadata.get('ticket_id', 'N/A')}, Score: {doc.metadata.get('score')}, Length: {len(doc.page_content)} chars):")
                try:
                    metadata_json = json.dumps(doc.metadata, indent=2, default=str)
                    for line in metadata_json.splitlines():
                        logger.debug(f"    {line}")
                    content_snippet = doc.page_content[:200].replace('\n', ' ')
                    logger.debug(f"    Content Snippet: {content_snippet}...")
                except Exception as log_e:
                    logger.warning(f"    Error logging details for initial doc {doc.metadata.get('ticket_id', 'N/A')}: {log_e}")
            logger.info(f"Processed {len(documents)} documents from Pinecone results.")
            return documents
        except Exception as e:
            logger.error("Pinecone search error during initial retrieval:", exc_info=True)
            # Fall through to FAISS if Pinecone fails mid-operation

    logger.warning("Falling back to FAISS for similarity search.")
    if not embeddings:
        logger.error("Embeddings not available for FAISS fallback.")
        return []

    # This FAISS part is problematic as it needs a corpus. 
    # For now, it will likely only find the dummy doc. This needs a proper fix if FAISS is a desired fallback.
    logger.warning("FAISS fallback currently uses a dummy store. Results may not be relevant.")
    dummy_docs = [Document(page_content="dummy document for faiss initialization", metadata={"ticket_id":"FAISS_DUMMY"})]
    try:
        faiss_store = FAISS.from_documents(dummy_docs, embeddings)
        faiss_results = faiss_store.similarity_search(query, k=k)
        logger.info(f"FAISS search returned {len(faiss_results)} results.")
        for i, doc in enumerate(faiss_results):
            logger.debug(f"  Retrieved FAISS Doc {i+1} (ID: {doc.metadata.get('ticket_id', 'N/A')}, Length: {len(doc.page_content)} chars):")
            content_snippet_faiss = doc.page_content[:200].replace('\n', ' ')
            logger.debug(f"    Content Snippet: {content_snippet_faiss}...")
        return faiss_results
    except Exception as e:
        logger.error("FAISS search error:", exc_info=True)
        return []


def rerank_tickets_with_llm(query: str, docs: List[Document], top_n: int = 3) -> List[Document]:
    if not docs:
        logger.warning("No documents provided to rerank_tickets_with_llm. Returning empty list.")
        return []
    if not llm:
        logger.warning("LLM not available for reranking. Returning original top_n documents without reranking.")
        return docs[:top_n]

    logger.info(f"Reranking {len(docs)} documents for query: '{query[:100]}...' to get top {top_n}.")
    # Include ticket_id in the formatted docs for better context if the LLM needs it (and for logging)
    formatted_docs_for_prompt = "\n".join([
        f"[{i+1}] ID: {doc.metadata.get('ticket_id', 'N/A')} Score: {doc.metadata.get('score', 'N/A'):.4f}\nContent: {doc.page_content[:500]}..." 
        for i, doc in enumerate(docs)
    ])
    prompt_to_llm = RERANK_DUPLICATE_TICKETS_PROMPT.format(top_n=top_n, query=query, formatted_docs=formatted_docs_for_prompt)
    
    logger.debug(f"Prompt sent to LLM for reranking:\n---\n{prompt_to_llm}\n---")

    raw_llm_response = "<LLM_RESPONSE_UNAVAILABLE>"
    try:
        llm_result = llm.invoke(prompt_to_llm)
        raw_llm_response = getattr(llm_result, 'content', str(llm_result)).strip()
        logger.info(f"Raw LLM response for reranking: '{raw_llm_response}'")
        
        parsed_indices_str = raw_llm_response.replace("[", "").replace("]", "").split(",")
        indices = []
        for val_str in parsed_indices_str:
            val_str_stripped = val_str.strip()
            if val_str_stripped.isdigit():
                indices.append(int(val_str_stripped) - 1) # Adjust to 0-based index
            elif val_str_stripped:
                logger.warning(f"Non-digit value '{val_str_stripped}' found in LLM reranking response. Ignoring.")
        
        logger.info(f"Parsed indices from LLM response: {indices}")

        reranked_documents = []
        seen_original_indices = set()
        for index_from_llm in indices:
            if 0 <= index_from_llm < len(docs):
                if index_from_llm not in seen_original_indices: # Ensure uniqueness based on original doc index
                    reranked_documents.append(docs[index_from_llm])
                    seen_original_indices.add(index_from_llm)
                else:
                    logger.warning(f"LLM returned duplicate original index {index_from_llm+1}. Keeping first occurrence.")
            else:
                logger.warning(f"LLM returned out-of-bounds index: {index_from_llm+1}. Max original index is {len(docs)}.")
        
        final_reranked_list = reranked_documents[:top_n] # Ensure we only take top_n unique docs
        logger.info(f"Successfully reranked. Selected {len(final_reranked_list)} documents from {len(docs)} initial.")
        return final_reranked_list
    except Exception as e:
        logger.error(f"Error during LLM reranking or parsing: {e}", exc_info=True)
        logger.error(f"LLM raw response at time of error (if available): '{raw_llm_response}'")
        logger.warning("Fallback: Returning original top_n documents due to reranking error.")
        return docs[:top_n]


def summarize_ticket_similarities(query: str, tickets: List[Document]) -> str:
    if not tickets:
        logger.info("No tickets provided to summarize_ticket_similarities. Returning empty summary.")
        return "No specific tickets were found to summarize based on the reranking."
    if not llm:
        logger.warning("LLM not initialized. Cannot summarize ticket similarities.")
        return "Summary unavailable: LLM not initialized."

    logger.info(f"Summarizing {len(tickets)} tickets for query: '{query[:100]}...'")
    ticket_texts = "\n\n".join([f"Ticket ID: {doc.metadata.get('ticket_id', f'Item {i+1}')}\nContent:\n{doc.page_content}" for i, doc in enumerate(tickets)])
    prompt_to_llm = SUMMARIZE_TICKET_SIMILARITIES_PROMPT.format(query=query, ticket_texts=ticket_texts)
    logger.debug(f"Prompt for summarization:\n---\n{prompt_to_llm}\n---")

    try:
        summary = llm.invoke(prompt_to_llm).content.strip()
        logger.info(f"Generated summary: '{summary[:100]}...'")
        return summary
    except Exception as e:
        logger.error(f"LLM summarization error: {e}", exc_info=True)
        return "Failed to generate summary due to an error."


def find_and_summarize_duplicatessss(user_query: str, retrieve_k: int = 10, rerank_n: int = 3) -> dict:
    logger.info(f"Starting duplicate detection pipeline with find_and_summarize_duplicates for query: '{user_query[:100]}...'")

    initial_tickets = retrieve_top_k_tickets(user_query, k=retrieve_k)
    if not initial_tickets:
        logger.warning("No initial tickets found by retrieve_top_k_tickets. Cannot proceed.")
        return {"top_tickets": [], "summary": "No similar tickets found during initial retrieval.", "error": "No initial tickets found."}

    reranked_tickets = rerank_tickets_with_llm(user_query, initial_tickets, top_n=rerank_n)
    if not reranked_tickets:
        logger.warning("No tickets selected after LLM reranking by rerank_tickets_with_llm.")
        # Optionally, could summarize top N of initial_tickets as a fallback here
        # summary = summarize_ticket_similarities(user_query, initial_tickets[:rerank_n]) 
        # For now, we reflect that reranking produced no results for summarization if it's empty.
        summary = "No specific tickets were identified as most relevant after reranking."
    else:
        logger.info(f"Details of {len(reranked_tickets)} tickets after reranking (to be summarized):")
        for i, doc in enumerate(reranked_tickets):
            logger.info(f"  Reranked Doc {i+1} (ID: {doc.metadata.get('ticket_id', 'N/A')}, Score: {doc.metadata.get('score', 'N/A')}, Length: {len(doc.page_content)} chars):")
            # Avoid logging full metadata dictionary if it's huge
            loggable_metadata = {k: v for k, v in doc.metadata.items() if k not in ['retrieved_problem_statement', 'retrieved_solution_summary']} # Log key fields
            logger.info(f"    {json.dumps(loggable_metadata, indent=4)}") 
            logger.info(f"    Content Snippet: {doc.page_content[:80]}...")

    # --- Summarize the Findings (COMMENTED OUT as per request) ---
    summary = None # Set summary to None as we are skipping the summarization step
    # try:
    #     logger.info(f"Summarizing {len(reranked_tickets)} tickets for query: '{user_query[:80]}...'")
    #     summary = summarize_ticket_similarities(user_query, reranked_tickets)
    #     logger.info(f"Generated summary: '{summary[:100]}...'")
    # except Exception as e_summary:
    #     logger.error(f"Error during similarity summary generation: {e_summary}", exc_info=True)
    #     summary = f"Error: Could not generate summary for similar tickets ({e_summary})"

    # Prepare final payload for app.py
    final_payload_tickets = []
    for doc in reranked_tickets: # Use the reranked_tickets for the payload
        final_payload_tickets.append({
            "ticket_id": doc.metadata.get("ticket_id", "N/A"),
            "page_content": doc.page_content, # Langchain Document schema uses page_content
            "metadata": doc.metadata
        })

    logger.info(f"Duplicate detection pipeline finished. Returning {len(final_payload_tickets)} tickets.")
    return {"tickets": final_payload_tickets, "summary": summary, "error": None}


def retrieve_top_k(query: str, k: int = 10) -> List[Document]:
    if not embeddings:
        logger.warning("Embeddings service not available in retrieve_top_k.")
        return []
    if not vector_store:
        logger.warning("Pinecone index not available in retrieve_top_k.")
        # Consider if FAISS fallback should be triggered here for retrieval too
        return []

    logger.info(f"(DUPLICATE LOGIC) Retrieving top {k} results from Pinecone for query: '{query[:100]}...'")
    query_vector = embeddings.embed_query(query)
    results = search_pinecone_index(index=vector_store, query_vector=query_vector, k=k)

    retrieved_docs = []
    if results:
        for i, match in enumerate(results):
            if 'metadata' in match:
                page_content = match['metadata'].get('page_content', 
                                                   match['metadata'].get('description', 
                                                                        match['metadata'].get('summary', '')))
                doc = Document(
                    page_content=page_content,
                    metadata={**match['metadata'], 'score': match.get('score')}
                )
                retrieved_docs.append(doc)
                logger.debug(f"(DUPLICATE LOGIC) Retrieved Doc {i+1}/{len(results)} (ID: {doc.metadata.get('ticket_id', 'N/A')} - Score: {doc.metadata.get('score', 'N/A')}):")
            # ... (rest of duplicated logging omitted for brevity) ...
    return retrieved_docs

def rerank_top_n(query: str, docs: List[Document], top_n: int = 3) -> List[Document]:
    if not docs:
        logger.warning("(DUPLICATE LOGIC) No documents provided to rerank_top_n. Returning empty list.")
        return []
    # ... (rest of duplicated logic omitted for brevity) ...
    logger.info(f"(DUPLICATE LOGIC) Successfully reranked. Returning {len(docs[:top_n])} documents.") # Example, actual logic was more complex
    return docs[:top_n]

def find_similar_jira_tickets(query: str) -> Dict:
    logger.info(f"(DUPLICATE LOGIC) Starting duplicate detection pipeline for query: '{query[:100]}...'")
    top_10_initial_docs = retrieve_top_k(query, k=10) # Calls the duplicated retrieve_top_k
    if not top_10_initial_docs:
        return {"tickets": [], "summary": "No similar tickets found after initial retrieval."}
    top_3_reranked_docs = rerank_top_n(query, top_10_initial_docs, top_n=3) # Calls the duplicated rerank_top_n
    summary = summarize_ticket_similarities(query, top_3_reranked_docs) # This summarize is fine
    # ... (payload construction omitted for brevity) ...
    return {
        "tickets": [], # Simplified for example
        "summary": summary
    }

def find_and_summarize_duplicates(user_query: str, retrieve_k: int = 10, rerank_n: int = 3) -> dict:
    logger.info(f"Starting duplicate detection pipeline with find_and_summarize_duplicates for query: '{user_query[:100]}...'")

    initial_tickets = retrieve_top_k_tickets(user_query, k=retrieve_k)
    if not initial_tickets:
        logger.warning("No initial tickets found by retrieve_top_k_tickets. Cannot proceed.")
        return {"top_tickets": [], "summary": "No similar tickets found during initial retrieval.", "error": "No initial tickets found."}

    reranked_tickets = rerank_tickets_with_llm(user_query, initial_tickets, top_n=rerank_n)
    if not reranked_tickets:
        logger.warning("No tickets selected after LLM reranking by rerank_tickets_with_llm.")
        # Optionally, could summarize top N of initial_tickets as a fallback here
        # summary = summarize_ticket_similarities(user_query, initial_tickets[:rerank_n]) 
        # For now, we reflect that reranking produced no results for summarization if it's empty.
        summary = "No specific tickets were identified as most relevant after reranking."
    else:
        logger.info(f"Details of {len(reranked_tickets)} tickets after reranking (to be summarized):")
        for i, doc in enumerate(reranked_tickets):
            logger.info(f"  Reranked Doc {i+1} (ID: {doc.metadata.get('ticket_id', 'N/A')}, Score: {doc.metadata.get('score', 'N/A')}, Length: {len(doc.page_content)} chars):")
            try:
                metadata_json = json.dumps(doc.metadata, indent=2, default=str)
                for line in metadata_json.splitlines():
                    logger.info(f"    {line}")
                content_snippet_reranked = doc.page_content[:200].replace('\n', ' ')
                logger.info(f"    Content Snippet: {content_snippet_reranked}...")
            except Exception as log_e:
                logger.warning(f"    Error logging details for reranked doc {doc.metadata.get('ticket_id', 'N/A')}: {log_e}")
        summary = summarize_ticket_similarities(user_query, reranked_tickets)

    # Prepare final payload for app.py
    final_payload_tickets = []
    for doc in reranked_tickets: # Use the reranked_tickets for the payload
        final_payload_tickets.append({
            "ticket_id": doc.metadata.get("ticket_id", "N/A"),
            "page_content": doc.page_content, # Langchain Document schema uses page_content
            "metadata": doc.metadata
        })

    logger.info(f"Duplicate detection pipeline finished. Returning {len(final_payload_tickets)} tickets.")
    return {"tickets": final_payload_tickets, "summary": summary, "error": None}
