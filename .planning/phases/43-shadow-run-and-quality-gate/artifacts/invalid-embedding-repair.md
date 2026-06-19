# Invalid Embedding Repair

- target_url: `surrealkv:///home/j2h4u/.cache/dotmd/phase43-target/phase43-fresh.surreal.db`
- target_namespace: `dotmd`
- target_database: `phase43_shadow`
- reason: HNSW index creation failed because 5 migrated embedding records had `array::len(embedding) = 0`.
- action: deleted only those invalid `embeddings` records; chunks/documents were not deleted.
- before_zero_dim_embeddings: `5`
- after_zero_dim_embeddings: `0`
- embeddings_after_repair: `149796`

Deleted chunk ids:

- `bb67f9a95a0600e8a2e74e1027743d8f2b8191b478495329d0426699e12048a1`
- `c0755273b99e6ee9afd5f8ccd3d4aba09eaea2ad296850ea82a88ec5e6910f52`
- `e379b01eaca0657dbf51f3045c9ca74ba39b4a808a49e66896bc0c8412b030f7`
- `256bbfcea7d2b0b9c1c2e10a40632c4f7b032df3f314a7fafb220108180ad00c`
- `2ad312b6cf7a5ba3160ba756cffcb77bff53987d1ebaff30ba76ac634b9fa41c`

Follow-up code change:

- Future migration now skips orphan `vec_meta` rows whose `vec_chunks` payload is absent, so they are not migrated as empty vectors.
