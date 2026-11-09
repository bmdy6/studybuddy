# Third-party components

This repository contains application source and dependency manifests. Dependencies retain their own licenses; the application license does not replace them.

- **PyMuPDF / MuPDF**: AGPL-3.0 or a separate Artifex commercial license. Used by the existing scanned-PDF rendering workflow. See [official licensing information](https://pymupdf.readthedocs.io/en/latest/about.html#license-and-copyright).
- **img2pdf**: LGPLv3, used for lossless photo-to-PDF assembly.
- **pdf-inspector**: MIT, used for text PDF extraction.
- **pypdf**: BSD-3-Clause.
- **OpenAI Python SDK**: Apache-2.0; API services have separate terms and usage charges.
- **KaTeX, remark-math, rehype-katex, unified and remark-parse**: MIT. Math rendering keeps KaTeX trust disabled and does not enable raw HTML. The added transitive math-rendering dependencies use MIT or ISC licenses; their notices remain in the package distributions.
- FastAPI, SQLAlchemy, React, Ant Design, Vite and other packages retain the license notices in their distributions. The complete direct dependency lists are in `studybuddy-backend/requirements.txt` and `studybuddy-client/package.json`; the client has a lockfile.

No model weights, external question bank corpus, student work, proprietary credential files or private deployment artifacts are bundled. External URLs in source adapters point to public providers or sources; access and redistribution rights for fetched material must be considered separately.
