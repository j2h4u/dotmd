# Vendored Airweave Slice Notes

- `entities_base.py`: replaced `SparseEmbedding` with a local stub, removed `airweave.domains` and `airweave.core` imports, and implemented local field-flag handling.
- `entities_gmail.py`: rewrote imports to `dotmd.vendor.airweave.*`; entity bodies and Gmail API factory methods are retained.
- `source_base.py`: replaced `ContextualLogger`, `AirweaveHttpClient`, and `SourceAuthProvider` with local structural stubs.
- `source_gmail.py`: rewrote imports, applies the local `@source` stub, and documents that `GmailSource.search()` is not implemented.
- `gmail_config.py`: extracted `GmailConfig` only and replaced Airweave config bases with `pydantic.BaseModel`.
- `decorators.py`: replaced the Airweave decorator implementation with a no-op stub that sets class attributes.
- `shims.py`: adds stdlib logging, `httpx.AsyncClient`, and OAuth refresh-token shims for dotMD runtime construction.
