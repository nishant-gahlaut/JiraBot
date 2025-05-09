import os
from pinecone import Index as PineconeIndex
from langchain_community.vectorstores import FAISS
from langchain.schema import Document
from typing import List, Optional

from .embedding_service import get_cohere_embeddings
from .genai_service import get_llm
from utils.prompts import RERANK_DUPLICATE_TICKETS_PROMPT, SUMMARIZE_TICKET_SIMILARITIES_PROMPT
# Import both functions from the refactored vector_store_service
from .vector_store_service import initialize_pinecone_vector_store, search_pinecone_index 

import logging
logger = logging.getLogger(__name__)

# Initialize components
embeddings = get_cohere_embeddings()
llm = get_llm()

# Attempt to initialize Pinecone vector store using the service
# The vector_store variable will now be a native Pinecone Index object or None
vector_store: Optional[PineconeIndex] = None 
if embeddings:
    logger.info("Attempting to initialize Pinecone vector store via service...")
    vector_store = initialize_pinecone_vector_store(embeddings) # This now returns a pinecone.Index or None
    if vector_store:
        logger.info("Pinecone index connection successful through vector_store_service.")
    else:
        logger.warning("Failed to initialize Pinecone index through vector_store_service. Will use FAISS fallback.")
else:
    logger.warning("Embeddings not available, skipping Pinecone vector store initialization. Will use FAISS fallback.")

# Step 1: Query embedding and top-k retrieval
def retrieve_top_k_tickets(query: str, k: int = 10) -> List[Document]:
    """Retrieves top-k similar documents from the vector store (Pinecone or FAISS)."""
    if vector_store and embeddings: # Pinecone native client usage
        try:
            logger.info(f"Attempting similarity search with Pinecone index for query: '{query[:50]}...'")
            query_embedding = embeddings.embed_query(query)
            # Assuming default namespace for now, or you might want to pass it from config
            pinecone_results = search_pinecone_index(index=vector_store, query_vector=query_embedding, k=k, namespace=None) 
            
            documents = []
            if pinecone_results:
                for match in pinecone_results:
                    # IMPORTANT: Adjust metadata field access based on how you store data in Pinecone.
                    # The Pinecone Quickstart used match['fields']['chunk_text'].
                    # Here, we assume a structure like: match['metadata']['page_content'] etc.
                    # You MUST ensure your Pinecone records have a metadata field that contains the text
                    # and other necessary details like ticket_id, url.
                    metadata_payload = match.get('metadata', {})
                    page_content = metadata_payload.get('page_content', metadata_payload.get('text', '')) # Fallback to 'text' field
                    
                    # Create a new dict for Langchain Document metadata to avoid modifying original
                    doc_metadata = metadata_payload.copy()
                    doc_metadata['score'] = match.get('score') # Add similarity score
                    # Ensure 'page_content' or 'text' is not duplicated in the metadata passed to Document
                    doc_metadata.pop('page_content', None)
                    doc_metadata.pop('text', None)

                    documents.append(Document(page_content=page_content, metadata=doc_metadata))
                logger.info(f"Pinecone search successful. Converted {len(documents)} results to Langchain Documents.")
            else:
                logger.info("Pinecone search returned no results.")
            return documents
        except Exception as e:
            logger.error(f"Error during Pinecone similarity search: {e}", exc_info=True)
            logger.warning("Falling back to FAISS due to error with Pinecone.")
            # Fall through to FAISS logic below
    
    # Fallback to a dummy FAISS if Pinecone wasn't initialized or search failed
    logger.warning("Configured vector store (Pinecone) not available or search failed. Using FAISS store.")
    if not embeddings:
        logger.error("Error: Embeddings not available for FAISS fallback. Cannot perform similarity search.")
        return []
        
    # Using a single dummy document to initialize FAISS if it's empty.
    # In a real scenario, this FAISS instance might be pre-populated or loaded on demand.
    documents_for_faiss = [Document(page_content="dummy document for faiss initialization")] 
    try:
        logger.info("Initializing FAISS store for fallback similarity search...")
        faiss_store = FAISS.from_documents(documents_for_faiss, embeddings)
        logger.info(f"Performing similarity search with FAISS for query: '{query[:50]}...'")
        return faiss_store.similarity_search(query, k=k) # FAISS search returns List[Document] directly
    except Exception as e:
        logger.error(f"Error during FAISS similarity search: {e}", exc_info=True)
        return []

# Step 2: Use LLM to rerank the top k tickets to top n
def rerank_tickets_with_llm(query: str, docs: List[Document], top_n: int = 3) -> List[Document]:
    """Reranks the given documents based on the query using an LLM."""
    if not docs:
        return []
    if not llm:
        print("LLM not initialized. Cannot rerank tickets.")
        return docs # Return original docs if LLM is not available

    # Format documents for the prompt
    formatted_docs = "\n".join([f"[{i+1}] {doc.page_content}" for i, doc in enumerate(docs)])

    prompt = RERANK_DUPLICATE_TICKETS_PROMPT.format(top_n=top_n, query=query, formatted_docs=formatted_docs)

    try:
        response = llm.invoke(prompt)
        content = response.content.strip()
        if not content or content.lower() == 'none':
            return []
        
        # Handle potential variations in LLM output for indices
        indices_str = content.replace('[', '').replace(']', '').split(',')
        valid_indices = []
        for i_str in indices_str:
            i_str = i_str.strip()
            if i_str.isdigit():
                idx = int(i_str) - 1 # LLM provides 1-based index
                if 0 <= idx < len(docs):
                    valid_indices.append(idx)
            else:
                print(f"Warning: LLM returned non-numeric or invalid index part: '{i_str}'")
        
        # Ensure no duplicate indices and preserve order if possible from LLM
        seen_indices = set()
        final_indices = []
        for idx in valid_indices:
            if idx not in seen_indices:
                final_indices.append(idx)
                seen_indices.add(idx)
        
        return [docs[i] for i in final_indices][:top_n] # Ensure we don't exceed top_n
    except Exception as e:
        print(f"Error during LLM reranking: {e}")
        # Fallback: return top_n of original docs if reranking fails
        return docs[:top_n]

# Step 3: Summarize similarities between top n tickets
def summarize_ticket_similarities(query: str, tickets: List[Document]) -> str:
    """Summarizes similarities between the query and the provided tickets using an LLM."""
    if not tickets:
        return "No tickets provided for summarization."
    if not llm:
        return "LLM not initialized. Cannot summarize ticket similarities."

    ticket_texts = "\n\n".join([f"Ticket {i+1}:\n{doc.page_content}" for i, doc in enumerate(tickets)])
    prompt = SUMMARIZE_TICKET_SIMILARITIES_PROMPT.format(query=query, ticket_texts=ticket_texts)

    try:
        response = llm.invoke(prompt)
        return response.content
    except Exception as e:
        print(f"Error during LLM summarization: {e}")
        return "Failed to generate summary due to an error."

# New orchestrator method
def find_and_summarize_duplicates(user_query: str, retrieve_k: int = 10, rerank_n: int = 3) -> dict:
    """
    Orchestrates the duplicate detection pipeline: retrieves, reranks, and summarizes tickets.

    Args:
        user_query: The user's query string to find duplicate tickets for.
        retrieve_k: The number of initial tickets to retrieve.
        rerank_n: The number of tickets to return after reranking.

    Returns:
        A dictionary containing:
            - "top_tickets": A list of reranked Document objects (up to rerank_n).
            - "summary": A string summarizing the similarities.
            - "error": An error message if any step failed critically, otherwise None.
    """
    print(f"Starting duplicate detection pipeline for query: '{user_query}'")

    # Step 1: Retrieve top-k tickets
    print(f"\nStep 1: Retrieving top {retrieve_k} initial tickets...")
    retrieved_tickets = retrieve_top_k_tickets(user_query, k=retrieve_k)
    if not retrieved_tickets:
        message = "No initial tickets found. Cannot proceed with reranking or summarization."
        print(message)
        return {"top_tickets": [], "summary": "", "error": message}
    print(f"Retrieved {len(retrieved_tickets)} initial tickets.")

    # Step 2: Rerank tickets
    print(f"\nStep 2: Reranking to top {rerank_n} tickets...")
    reranked_tickets = rerank_tickets_with_llm(user_query, retrieved_tickets, top_n=rerank_n)
    if not reranked_tickets:
        # If reranking returns empty, it might mean none were deemed relevant by the LLM.
        # We might still want to summarize the initially retrieved ones, or handle as an error.
        # For now, let's consider it a point where we might not have good candidates for summary.
        message = "No tickets selected after LLM reranking. Cannot proceed with summarization of reranked tickets."
        print(message)
        # Optionally, could summarize the original top_10 or a subset.
        # For this example, we return based on the reranked set.
        return {"top_tickets": [], "summary": "", "error": message}
    print(f"Reranked to {len(reranked_tickets)} tickets.")

    # Step 3: Summarize similarities
    print("\nStep 3: Summarizing similarities among reranked tickets...")
    similarity_summary = summarize_ticket_similarities(user_query, reranked_tickets)
    print("Summarization complete.")

    return {
        "top_tickets": reranked_tickets,
        "summary": similarity_summary,
        "error": None
    }

# Example Usage (optional, for testing)
if __name__ == '__main__':
    print("Duplicate Detection Service - Orchestrator Example Run")
    print("-----------------------------------------------------")

    sample_query = "Login button not working on Safari browser"
    print(f"Sample Query: {sample_query}\n")

    # Call the new orchestrator method
    results = find_and_summarize_duplicates(sample_query)

    if results.get("error"):
        print(f"\nPipeline Error: {results['error']}")
    else:
        print("\n--- Top Ranked Tickets ---")
        if results["top_tickets"]:
            for i, doc in enumerate(results["top_tickets"], 1):
                ticket_id = doc.metadata.get('ticket_id', 'N/A') # Example: assuming ticket_id in metadata
                print(f"Ticket {i} ID: {ticket_id}")
                print(f"Content: {doc.page_content[:200]}...\n") # Print first 200 chars
        else:
            print("No tickets were ranked as relevant.")

        print("\n--- Summary of Similarities ---")
        print(results["summary"])

    print("\n-----------------------------------------------------")
    print("Orchestrator example run finished.")

