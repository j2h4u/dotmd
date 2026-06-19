DEFINE INDEX embeddings_strategy_chunk_model_idx ON TABLE embeddings COLUMNS chunk_strategy, chunk_id, embedding_model UNIQUE;
DEFINE INDEX embeddings_strategy_model_idx ON TABLE embeddings COLUMNS chunk_strategy, embedding_model;
DEFINE INDEX embeddings_text_hash_idx ON TABLE embeddings COLUMNS text_hash;
DEFINE INDEX embeddings_hnsw_idx ON TABLE embeddings COLUMNS embedding HNSW DIMENSION 1024 DIST COSINE EFC 64;
