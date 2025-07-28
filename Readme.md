## 🧠 Approach

This solution uses a heuristic-based approach to extract structured headings (H1, H2, H3) from PDF documents. The main components include:

- **Two-pass strategy**: 
  - **Pass 1**: Identifies repetitive content (like headers/footers) using spatial and textual repetition analysis.
  - **Pass 2**: Extracts text lines, computes features (font size, bold, indentation, keywords, etc.), and scores each line to determine if it is a heading.

- **Heading scoring**: Each line is scored based on font size ratio, boldness, position, enumeration patterns (like `1.1`, `I.`, etc.), presence of cue words, and spacing.

- **Multi-line heading merging**: Lines close in position, font, and format are merged to handle split headings.

- **Level classification (H1/H2/H3)**: Based on font hierarchy, enumeration structure, and indentation.

- **Title extraction**: The largest, top-most, centered text on the first page is selected as the document title.

## 🧰 Libraries Used

- [`PyMuPDF`](https://pymupdf.readthedocs.io/en/latest/) (`fitz`): For reading and parsing PDFs.
- `re`: Regular expressions for pattern matching.
- `statistics`, `collections`, `os`, `argparse`, `logging`, `json`, `sys`, `typing`: For feature calculations, parsing, and I/O operations.

## 📦 Expected Execution

> My solution is expected to be run in a Docker-like environment with the following constraints:
>
> - Input PDFs placed in `/app/input`
> - Output JSONs written to `/app/output`
> - Script automatically processes all `.pdf` files in the input directory

## ▶️ How to Build and Run (For Documentation Purposes Only)

1. **Install dependencies** (ensure Python 3.8+):
   ```bash
   pip install PyMuPDF
````

2. **Run the script**:

   ```bash
   python 1a.py --input-dir ./input --output-dir ./output
   ```

   * This will process all `.pdf` files in `./input` and write `.json` files to `./output`.

## ✅ Highlights

* Handles noisy headers/footers through pre-processing.
* Uses strict heuristics to avoid false positives.
* Outputs are clean and human-interpretable JSON files.
* Logging is built-in for debugging and traceability (can be enhanced by uncommenting `LOG_FILE_PATH` in the script).

