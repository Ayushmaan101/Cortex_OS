from sentence_transformers import SentenceTransformer
import numpy as np

# We'll use a reliable, lightweight model for local dev
# Note: For production 1536 dims, we'd usually use OpenAI or a larger local model.
# For this Phase, we'll use a standard model and "pad" or use a 1536-compatible one.
model = SentenceTransformer('all-MiniLM-L6-v2')

def get_embedding(text: str):
    # Generate embedding (this model produces 384 dims)
    embedding = model.encode(text)
    
    # To match your 1536-dim column for now, we will pad with zeros 
    # This allows us to test the 'plumbing' without a massive 10GB model download
    padded_embedding = np.zeros(1536)
    padded_embedding[:len(embedding)] = embedding
    
    return padded_embedding.tolist()