import logging
import os
import json
from typing import List, Optional, Dict
from pinecone import Index as PineconeIndex
from langchain_community.vectorstores import FAISS
from langchain.schema import Document
import time

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
    MIN_PINECONE_SCORE_FOR_LLM_CANDIDACY = float(os.environ.get("MIN_PINECONE_SCORE_THRESHOLD", "0.50"))  # Get threshold from env var with default

    if vector_store and embeddings:
        try:
            query_embedding = embeddings.embed_query(query)
            logger.debug(f"Query embedded. Searching Pinecone index...")
            results = search_pinecone_index(index=vector_store, query_vector=query_embedding, k=k, namespace=None)
            logger.info(f"Pinecone search returned {len(results) if results else 0} raw matches.")

            for i, match in enumerate(results):
                metadata = match.get('metadata', {})
                content = metadata.get('page_content', 
                                     metadata.get('description', 
                                                  metadata.get('summary', '')))
                if 'page_content' in metadata and content == metadata['page_content']:
                    metadata_for_doc = metadata.copy()
                else:
                    metadata_for_doc = metadata
                
                metadata_for_doc['score'] = match.get('score')
                doc = Document(page_content=content, metadata=metadata_for_doc)
                documents.append(doc)
                # Reduced logging here as we will log filtered docs later
                # logger.debug(f"  Retrieved Raw Doc {i+1} (ID: {doc.metadata.get('ticket_id', 'N/A')}, Score: {doc.metadata.get('score')})")

            logger.info(f"Processed {len(documents)} raw documents from Pinecone results.")

            # Log all raw documents and their scores before filtering
            if documents:
                logger.info(f"--- Scores for {len(documents)} raw documents retrieved from Pinecone (before filtering) ---")
                for i, doc in enumerate(documents):
                    raw_score = doc.metadata.get('score', 'N/A')
                    raw_ticket_id = doc.metadata.get('ticket_id', 'N/A')
                    logger.info(f"  Raw Doc {i+1}: ID: {raw_ticket_id}, Score: {raw_score if isinstance(raw_score, str) else f'{raw_score:.4f}'}")
                logger.info("-------------------------------------------------------------------")

            # Filter documents based on the score threshold
            filtered_documents = []
            if documents:
                logger.info(f"Filtering {len(documents)} documents with threshold: score >= {MIN_PINECONE_SCORE_FOR_LLM_CANDIDACY}")
                for doc in documents:
                    score = doc.metadata.get('score', 0.0) # Default to 0.0 if score is missing
                    if score >= MIN_PINECONE_SCORE_FOR_LLM_CANDIDACY:
                        filtered_documents.append(doc)
                        logger.info(f"  KEEPING Doc ID: {doc.metadata.get('ticket_id', 'N/A')}, Score: {score:.4f}")
                    else:
                        logger.debug(f"  FILTERING OUT Doc ID: {doc.metadata.get('ticket_id', 'N/A')}, Score: {score:.4f} (Below threshold)")
                logger.info(f"{len(filtered_documents)} documents remaining after score filtering.")
            else:
                logger.info("No documents retrieved from Pinecone to filter.")
            
            return filtered_documents
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


def rerank_tickets_with_llm(query: str, docs: List[Document], top_n: int = 5) -> List[Document]:
    if not docs:
        logger.warning("No documents provided to rerank_tickets_with_llm. Returning empty list.")
        return []
    if not llm:
        logger.warning("LLM not available for reranking. Returning original top_n documents without reranking.")
        # Fallback: return original docs, perhaps sorted by initial score if available, up to top_n
        # This is a simple fallback, could be made more sophisticated
        sorted_docs_by_score = sorted(docs, key=lambda d: d.metadata.get('score', 0.0), reverse=True)
        return sorted_docs_by_score[:top_n]

    logger.info(f"Reranking {len(docs)} documents for query: '{query[:100]}...' using LLM to make YES/NO decisions.")
    
    # Prepare documents for the prompt, ensuring 1-based indexing for `original_index`
    formatted_docs_for_prompt_list = []
    for i, doc in enumerate(docs):
        ticket_id = doc.metadata.get('ticket_id', 'N/A')
        pinecone_score = doc.metadata.get('score', 'N/A')
        score_str = f"{pinecone_score:.4f}" if isinstance(pinecone_score, float) else str(pinecone_score)
        # Ensure content is not overly long for the prompt
        content_snippet = doc.page_content[:1000] # Increased snippet length for better context
        if len(doc.page_content) > 1000:
            content_snippet += "... (truncated)"
        formatted_docs_for_prompt_list.append(
            f"[{i+1}] Ticket ID: {ticket_id} | Pinecone Score: {score_str}\nContent: {content_snippet}"
        )
    formatted_docs_str = "\n\n".join(formatted_docs_for_prompt_list)

    # Note: The new prompt does not use {top_n} directly in its template for LLM response generation count.
    # The LLM should process all documents and we will filter/sort later based on its response.
    prompt_to_llm = RERANK_DUPLICATE_TICKETS_PROMPT.format(query=query, formatted_docs=formatted_docs_str)
    
    logger.debug(f"Prompt sent to LLM for reranking decision (first 500 chars):\n---\n{prompt_to_llm[:500]}...\n---")

    raw_llm_response = "<LLM_RESPONSE_UNAVAILABLE>"
    try:
        llm_result = llm.invoke(prompt_to_llm)
        raw_llm_response = getattr(llm_result, 'content', str(llm_result)).strip()
        logger.info(f"Raw LLM response for reranking (first 300 chars): '{raw_llm_response[:300]}...'")
        
        # Clean potential markdown ```json ... ```
        cleaned_llm_response = raw_llm_response
        if cleaned_llm_response.startswith("```json"):
            cleaned_llm_response = cleaned_llm_response[len("```json"):].strip()
        if cleaned_llm_response.endswith("```"):
            cleaned_llm_response = cleaned_llm_response[:-len("```")].strip()

        llm_evaluations = json.loads(cleaned_llm_response)
        
        if not isinstance(llm_evaluations, list):
            logger.error(f"LLM response was not a list as expected. Response: {cleaned_llm_response}")
            raise ValueError("LLM response was not a list.")

        logger.info(f"Successfully parsed {len(llm_evaluations)} evaluations from LLM.")

        accepted_documents_with_scores = []
        for eval_item in llm_evaluations:
            if not isinstance(eval_item, dict):
                logger.warning(f"Skipping invalid item in LLM response (not a dict): {eval_item}")
                continue

            is_similar = eval_item.get('is_similar')
            llm_score = eval_item.get('llm_similarity_score')
            original_index_1_based = eval_item.get('original_index')
            ticket_id_from_llm = eval_item.get('ticket_id') # For logging/verification
            reasoning = eval_item.get('reasoning', 'No reasoning provided.')

            if is_similar == "YES":
                if isinstance(llm_score, (float, int)) and isinstance(original_index_1_based, int):
                    original_index_0_based = original_index_1_based - 1
                    if 0 <= original_index_0_based < len(docs):
                        doc_to_add = docs[original_index_0_based]
                        # Store LLM score for sorting, and also original Pinecone score for reference if needed
                        doc_to_add.metadata['llm_similarity_score'] = float(llm_score)
                        doc_to_add.metadata['llm_reasoning'] = reasoning
                        doc_to_add.metadata['llm_decision'] = "YES"
                        accepted_documents_with_scores.append(doc_to_add)
                        logger.info(f"  LLM ACCEPTED: Ticket ID {ticket_id_from_llm} (Original Index {original_index_1_based}), LLM Score: {llm_score:.4f}, Pinecone: {doc_to_add.metadata.get('score', 'N/A'):.4f}. Reason: {reasoning}")
                    else:
                        logger.warning(f"LLM returned valid 'YES' but out-of-bounds original_index: {original_index_1_based}. Max original index is {len(docs)}.")
                else:
                    logger.warning(f"LLM returned 'YES' but with invalid score ('{llm_score}') or index ('{original_index_1_based}') for ticket {ticket_id_from_llm}. Skipping.")
            elif is_similar == "NO":
                 logger.info(f"  LLM REJECTED: Ticket ID {ticket_id_from_llm} (Original Index {original_index_1_based}), LLM Score: {llm_score if isinstance(llm_score, (float,int)) else 'N/A'}, Pinecone: {docs[original_index_1_based-1].metadata.get('score', 'N/A') if 0 <= original_index_1_based-1 < len(docs) else 'N/A'}. Reason: {reasoning}")
                 # Optionally, store NO decisions if needed for analysis later, e.g., in doc.metadata
                 if isinstance(original_index_1_based, int) and 0 <= original_index_1_based -1 < len(docs):
                     docs[original_index_1_based-1].metadata['llm_decision'] = "NO"
                     if isinstance(llm_score, (float, int)):
                         docs[original_index_1_based-1].metadata['llm_similarity_score'] = float(llm_score)
                     if reasoning:
                         docs[original_index_1_based-1].metadata['llm_reasoning'] = reasoning
            else:
                logger.warning(f"LLM returned unknown 'is_similar' value: '{is_similar}' for ticket {ticket_id_from_llm}. Skipping.")

        # Sort the accepted documents by LLM similarity score in descending order
        sorted_accepted_documents = sorted(accepted_documents_with_scores, key=lambda d: d.metadata.get('llm_similarity_score', 0.0), reverse=True)
        
        final_reranked_list = sorted_accepted_documents[:top_n] # Apply top_n to the LLM-approved and sorted list
        logger.info(f"LLM processing complete. Selected {len(final_reranked_list)} documents out of {len(docs)} initial candidates (after 'YES' filter and sorting by LLM score). Target top_n was {top_n}.")
        return final_reranked_list
        
    except json.JSONDecodeError as e:
        logger.error(f"Error decoding JSON from LLM response: {e}", exc_info=True)
        logger.error(f"LLM raw response at time of JSON error: '{raw_llm_response}'")
        logger.warning("Fallback: Returning original top_n documents (sorted by Pinecone score) due to LLM JSON parsing error.")
        sorted_docs_by_score = sorted(docs, key=lambda d: d.metadata.get('score', 0.0), reverse=True)
        return sorted_docs_by_score[:top_n]
    except Exception as e:
        logger.error(f"Error during LLM reranking or parsing: {e}", exc_info=True)
        logger.error(f"LLM raw response at time of error (if available): '{raw_llm_response}'")
        logger.warning("Fallback: Returning original top_n documents (sorted by Pinecone score) due to general reranking error.")
        sorted_docs_by_score = sorted(docs, key=lambda d: d.metadata.get('score', 0.0), reverse=True)
        return sorted_docs_by_score[:top_n]


def find_and_summarize_duplicates_mention_flow(user_query: str, retrieve_k: int = 20, rerank_n: int = 5) -> dict:
    logger.info(f"Starting duplicate detection pipeline with find_and_summarize_duplicates for query: '{user_query[:100]}...'")

    initial_tickets = retrieve_top_k_tickets(user_query, k=retrieve_k)
    if not initial_tickets:
        logger.warning("No initial tickets found by retrieve_top_k_tickets. Cannot proceed.")
        return {"tickets": [], "error": "No initial tickets found."}

    reranked_tickets = rerank_tickets_with_llm(user_query, initial_tickets, top_n=rerank_n)
    if not reranked_tickets:
        logger.warning("No tickets selected after LLM reranking by rerank_tickets_with_llm.")
        return {"tickets": [], "error": "No tickets selected after reranking."}

    logger.info(f"Details of {len(reranked_tickets)} tickets after reranking:")
    for i, doc in enumerate(reranked_tickets):
        logger.info(f"  Reranked Doc {i+1} (ID: {doc.metadata.get('ticket_id', 'N/A')}, Score: {doc.metadata.get('score', 'N/A')}, Length: {len(doc.page_content)} chars):")
        # Avoid logging full metadata dictionary if it's huge
        loggable_metadata = {k: v for k, v in doc.metadata.items() if k not in ['retrieved_problem_statement', 'retrieved_solution_summary']} # Log key fields
        logger.info(f"    {json.dumps(loggable_metadata, indent=4)}") 
        logger.info(f"    Content Snippet: {doc.page_content[:80]}...")

    # Prepare final payload for app.py
    final_payload_tickets = []
    for doc in reranked_tickets:
        final_payload_tickets.append({
            "ticket_id": doc.metadata.get("ticket_id", "N/A"),
            "page_content": doc.page_content,
            "metadata": doc.metadata
        })

    logger.info(f"Duplicate detection pipeline finished. Returning {len(final_payload_tickets)} tickets.")
    return {"tickets": final_payload_tickets, "error": None}


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

def summarize_ticket_similarities(query: str, docs: List[Document]) -> str:
    if not docs:
        logger.warning("No documents provided to summarize_ticket_similarities. Returning empty summary.")
        return "No similar tickets found to summarize."
    if not llm:
        logger.warning("LLM not available for summarization. Returning empty summary.")
        return "Error: LLM service not available for summarization."

    logger.info(f"Summarizing {len(docs)} tickets for query: '{query[:100]}...'")
    formatted_docs_for_prompt = "\n".join([
        f"[{i+1}] ID: {doc.metadata.get('ticket_id', 'N/A')} Score: {doc.metadata.get('score', 'N/A'):.4f}\nContent: {doc.page_content[:500]}..." 
        for i, doc in enumerate(docs)
    ])
    prompt_to_llm = SUMMARIZE_TICKET_SIMILARITIES_PROMPT.format(query=query, formatted_docs=formatted_docs_for_prompt)
    
    logger.debug(f"Prompt sent to LLM for summarization:\n---\n{prompt_to_llm}\n---")

    try:
        llm_result = llm.invoke(prompt_to_llm)
        summary = getattr(llm_result, 'content', str(llm_result)).strip()
        logger.info(f"Generated summary: '{summary[:100]}...'")
        return summary
    except Exception as e:
        logger.error(f"Error during LLM summarization: {e}", exc_info=True)
        return f"Error: Could not generate summary for similar tickets ({e})"

def find_and_summarize_duplicates(user_query: str, retrieve_k: int = 20, rerank_n: int = 5) -> dict:
    logger.info(f"Starting duplicate detection pipeline with find_and_summarize_duplicates for query: '{user_query[:100]}...'")

    # 1. Retrieve top k tickets
    start_time_retrieve = time.time()
    initial_tickets = retrieve_top_k_tickets(user_query, k=retrieve_k)
    end_time_retrieve = time.time()
    logger.info(f"Retrieving top {retrieve_k} tickets took {end_time_retrieve - start_time_retrieve:.2f} seconds")
    
    if not initial_tickets:
        logger.warning("No initial tickets found by retrieve_top_k_tickets. Cannot proceed.")
        return {"tickets": [], "error": "No initial tickets found."}

    # 2. Rerank tickets
    start_time_rerank = time.time()
    reranked_tickets = rerank_tickets_with_llm(user_query, initial_tickets, top_n=rerank_n)
    end_time_rerank = time.time()
    logger.info(f"Reranking {len(initial_tickets)} tickets took {end_time_rerank - start_time_rerank:.2f} seconds")

    if not reranked_tickets:
        logger.warning("No tickets selected after LLM reranking by rerank_tickets_with_llm.")
        return {"tickets": [], "error": "No tickets selected after reranking."}

    logger.info(f"Details of {len(reranked_tickets)} tickets after reranking:")
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

    # Prepare final payload for app.py
    final_payload_tickets = []
    for doc in reranked_tickets:
        final_payload_tickets.append({
            "ticket_id": doc.metadata.get("ticket_id", "N/A"),
            "page_content": doc.page_content,
            "metadata": doc.metadata
        })

    logger.info(f"Duplicate detection pipeline finished. Returning {len(final_payload_tickets)} tickets.")
    return {"tickets": final_payload_tickets, "error": None}
