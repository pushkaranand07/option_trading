# Vendored libraries

The page's three JavaScript libraries, copied byte for byte from their CDNs on 2026-11-09 and served by this server
at `/static/vendor/...`. No CDN is contacted when the page loads, so it works offline and a changed CDN file cannot
reach the page. `tests/test_audit_e_vendor.py` checks each file against the SHA-384 below.

| File | Version | Source URL | SHA-384 |
|---|---|---|---|
| `lightweight-charts-4.2.0.standalone.production.js` | 4.2.0 | https://unpkg.com/lightweight-charts@4.2.0/dist/lightweight-charts.standalone.production.js | `sha384-OK7vELvjHdhUFi31JYioPIcRHTROLdcDa6ZsNWgvgLaKj+9JqhU0Ad8g4wz3CXjA` |
| `marked-12.0.2.min.js` | 12.0.2 | https://cdnjs.cloudflare.com/ajax/libs/marked/12.0.2/marked.min.js | `sha384-/TQbtLCAerC3jgaim+N78RZSDYV7ryeoBCVqTuzRrFec2akfBkHS7ACQ3PQhvMVi` |
| `purify-3.1.6.min.js` (DOMPurify) | 3.1.6 | https://cdnjs.cloudflare.com/ajax/libs/dompurify/3.1.6/purify.min.js | `sha384-+VfUPEb0PdtChMwmBcBmykRMDd+v6D/oFmB3rZM/puCMDYcIvF968OimRh4KQY9a` |

How each download was checked against a hash its CDN publishes:

- **marked, DOMPurify:** the cdnjs API (`https://api.cdnjs.com/libraries/<name>/<version>?fields=sri`) publishes
  SHA-512 SRI. Both files match it: marked
  `sha512-xeUh+KxNyTufZOje++oQHstlMQ8/rpyzPuM+gjMFYK3z5ILJGE7l2NvYL+XfliKURMpBIKKp1XoPN/qswlSMFA==`, DOMPurify
  `sha512-jB0TkTBeQC9ZSkBqDhdmfTv1qdfbWpGE72yJ/01Srq6hEzZIz2xkz1e57p9ai7IeHMwEG7HpzG6NdptChif5Pg==`.
- **lightweight-charts:** unpkg publishes no SRI. The file matches the SHA-256 that jsDelivr lists for the same npm
  package file (`https://data.jsdelivr.com/v1/package/npm/lightweight-charts@4.2.0/flat`):
  `sha256-RvxpU07AmPCVu80dmibWk9Oai57v9zQ1NnZbPdKMK98=`, 163,551 bytes.

The file names carry the version, so a browser never mixes an old cached copy with a new one; the server adds
`?v=<mtime>` only to `app.js` and `style.css`. To update a library: download the new version under a new versioned
name, check it against the CDN's published hash, update `index.html`, this table and the test's file list.

The page still loads Inter from Google Fonts (`index.html`); without it the browser uses the system font stack.
