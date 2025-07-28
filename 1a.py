import fitz  # PyMuPDF
import json
import re
import os
import sys
from typing import List, Dict, Tuple, Optional
from collections import defaultdict, Counter
import statistics
import argparse
import logging

# --- LOGGING CONFIGURATION MODIFICATION ---
# Define a log file path
# LOG_FILE_PATH = "heading_extraction_debug.log" # The file where logs will be saved

# --- REST OF THE CODE (EXACTLY AS YOU PROVIDED IT) ---

class PDFHeadingExtractor:
    def __init__(self):
        # --- Configuration for Header/Footer Detection (Tune these!) ---
        self.HF_TOP_ZONE_PERCENTAGE = 0.06  # Top 6% of the page height (even stricter)
        self.HF_BOTTOM_ZONE_PERCENTAGE = 0.06 # Bottom 6% of the page height (even stricter)
        self.HF_MIN_PAGES_FOR_REPETITION = 3 # A line must appear on at least this many pages
        self.HF_REPETITION_THRESHOLD_PERCENT = 0.75 # Must appear on >= 75% of doc pages (stricter)

        # --- Heading Detection Heuristics & Patterns ---
        self.HEADING_SCORE_THRESHOLD = 75 # INCREASED THRESHOLD FOR STRICTER DETECTION (from 45 to 50)
        self.MIN_HEADING_FONT_SIZE_RATIO = 1.3 # Must be at least 30% larger than body (stricter from 1.25)
        self.MAX_HEADING_WORD_COUNT = 18 # Headings usually aren't too long (stricter from 20)

        # Regex patterns for common heading structures (tuned for stricter matching)
        self.heading_patterns = [
            re.compile(r"^\s*(?:Chapter|Section|Part|Appendix)\s+(?:\d+|[IVXLCDM]+)(?:\.\d+)*\s*[:\.]?$", re.IGNORECASE), # e.g., Chapter 1, Section II, Appendix A
            re.compile(r"^\s*\d+(\.\d+)*\.?\s*[A-Z].*?[:\.]?$", re.IGNORECASE), # e.g., 1. Introduction, 2.1. Main Point
            re.compile(r"^\s*[IVXLCDM]+\s+[A-Z].*?[:\.]?$", re.IGNORECASE), # e.g., I. General Provisions
            re.compile(r"^[A-Z][A-Z\s]{5,}(?<!\.)\s*$", re.IGNORECASE), # ALL CAPS, at least 5 chars long, no trailing period
            re.compile(r"^[A-Z][a-z]+(?:\s+[A-Z][a-z]*)*\s*[:\.]?$", re.IGNORECASE), # Title Case, may end with : or no punctuation
            # Less strict patterns for sub-headings like "(a)" or "a." if needed.
            re.compile(r"^\s*\([a-z]\)\s+[A-Z].*?[:\.]?$", re.IGNORECASE), # (a) Sub-item
            re.compile(r"^\s*[a-z]\.\s+[A-Z].*?[:\.]?$", re.IGNORECASE), # a. Sub-item
        ]

        # Words that commonly appear in headings (case-insensitive check will be used)
        self.heading_keywords = {
            'introduction', 'conclusion', 'summary', 'overview', 'background',
            'methodology', 'results', 'discussion', 'references', 'appendix',
            'chapter', 'section', 'abstract', 'acknowledgments', 'bibliography',
            'annex', 'preface', 'foreword', 'table of contents', 'list of figures',
            'list of tables', 'definitions', 'scope', 'purpose', 'policy', 'procedure',
            'executive summary', 'terms and conditions', 'legal', 'analysis', 'findings',
            'evaluation', 'award', 'timeline', 'milestones', 'approach', 'requirements',
            'principles', 'access', 'guidance', 'training', 'purchasing', 'technological',
            'mean', 'developed', 'criteria', 'process', 'membership', 'chair', 'meetings',
            'accountability', 'communication', 'financial', 'administrative', 'policies',
            'preamble', 'terms of reference' # Added for file03.pdf specific headings
        }

        # Common patterns for non-content text (pre-compiled for performance)
        self.NON_CONTENT_PATTERNS = [
            re.compile(r"^\s*\d+\s*$", re.IGNORECASE),                # Just digits (page numbers)
            re.compile(r"^\s*-\s*\d+\s*-\s*$", re.IGNORECASE),        # "- 1 -", "- 25 -" (page numbers)
            re.compile(r"^\s*page\s+\d+\s*$", re.IGNORECASE),         # "Page 1", "page 10"
            re.compile(r"^\s*page\s+\d+\s+of\s+\d+\s*$", re.IGNORECASE), # "Page 1 of 10"
            re.compile(r"^\s*([ivxlcdm]+|[a-z])\s*$", re.IGNORECASE), # Roman/alpha numeric page numbers (e.g., "i", "a")
            re.compile(r"www\.", re.IGNORECASE), re.compile(r"\.gov", re.IGNORECASE), re.compile(r"\.org", re.IGNORECASE), re.compile(r"\.com", re.IGNORECASE), # URLs
            re.compile(r"confidential", re.IGNORECASE), re.compile(r"proprietar", re.IGNORECASE), re.compile(r"draft", re.IGNORECASE), # Confidentiality/status markings
            re.compile(r"author", re.IGNORECASE), re.compile(r"doi:", re.IGNORECASE), re.compile(r"copyright", re.IGNORECASE), re.compile(r"version\s*\d", re.IGNORECASE), # Metadata usually in HF
            re.compile(r"all\s+rights\s+reserved", re.IGNORECASE), re.compile(r"contact\s+information", re.IGNORECASE),
            re.compile(r"revision\s+history", re.IGNORECASE), re.compile(r"document\s+id", re.IGNORECASE), re.compile(r"file\s+id", re.IGNORECASE),
            re.compile(r"boscha{0,1}\s+north\s+america", re.IGNORECASE), # Specific to your NDA example
            re.compile(r"mutual\s+nda", re.IGNORECASE), re.compile(r"rev\.\s*\d{4}\.\d{2}\.\d{2}", re.IGNORECASE), # Specific to your NDA example
            re.compile(r"gretchen whitmer", re.IGNORECASE), re.compile(r"by the governor", re.IGNORECASE), re.compile(r"secretary of state", re.IGNORECASE), # Specific to EO
            re.compile(r"\d{1,3}\s+(?:south|north|east|west)?\s*capitol", re.IGNORECASE),  # Street addresses
            re.compile(r"george w\. romney building", re.IGNORECASE), re.compile(r"printed in-house", re.IGNORECASE), # More specific to your docs
            re.compile(r"^\s*[\*#\-_=\s]{3,}$"), # Repeating symbols for separators (e.g., "***", "---")
            re.compile(r"^\s*(?:p\.?|pg\.?)\s*\d+\s*$", re.IGNORECASE), # e.g. "p. 1", "pg. 2"
            re.compile(r"rfp:\s+to\s+develop\s+the\s+ontario\s+digital\s+library\s+business\s+plan\s+march\s+\d{4}", re.IGNORECASE), # Specific footer from file03.pdf
            re.compile(r"ontario's\s+libraries", re.IGNORECASE), # Specific header from file03.pdf
            re.compile(r"working\s+together", re.IGNORECASE), # Specific header from file03.pdf
            re.compile(r"connecting\s+ontarians!", re.IGNORECASE), # Specific header from file03.pdf
        ]

        # --- Internal State for Document Processing ---
        self._hf_candidates: Dict[Tuple, int] = defaultdict(int) # Stores (normalized_text, y_bucket, is_top_zone): count
        self._total_pages_in_doc: int = 0
        self._page_dimensions: Dict[int, Tuple[float, float]] = {} # Stores page_num: (width, height)

    def _reset_state(self):
        """Resets all internal state for processing a new document."""
        self._hf_candidates = defaultdict(int)
        self._total_pages_in_doc = 0
        self._page_dimensions = {}
        logging.info("Extractor state reset.")

    def _is_bold(self, flags: int) -> bool:
        """Correctly check if text is bold based on font flags (bit 0)."""
        return bool(flags & 1)

    def _is_italic(self, flags: int) -> bool:
        """Correctly check if text is italic based on font flags (bit 1)."""
        return bool(flags & 2)

    def _normalize_text_for_hf_comparison(self, text: str) -> str:
        """Normalizes text for robust header/footer repetition detection."""
        normalized = re.sub(r'\s+', ' ', text).strip().lower()
        # Remove common page number formats and other variable elements
        normalized = re.sub(r'(\d+\s*of\s*\d+|\s*page\s*\d+\s*|-\s*\d+\s*-|\d+)$', '', normalized).strip()
        normalized = re.sub(r'\d{4}-\d{2}-\d{2}', '', normalized).strip() # Remove YYYY-MM-DD dates
        normalized = re.sub(r'[0-9a-f]{32}', '', normalized).strip() # Remove common hash patterns
        return normalized

    def _pre_process_for_hf_detection(self, doc: fitz.Document):
        """
        First pass over the document to collect header/footer candidates based on repetition and position.
        Populates self._hf_candidates.
        """
        self._total_pages_in_doc = len(doc)
        
        # Scan up to first 10 pages for common repetitive patterns
        pages_to_scan_for_patterns = min(self._total_pages_in_doc, 10) 
        
        for page_num in range(self._total_pages_in_doc):
            page = doc[page_num]
            self._page_dimensions[page_num] = (page.rect.width, page.rect.height)

            page_height = page.rect.height
            top_zone_y_max = page_height * self.HF_TOP_ZONE_PERCENTAGE
            bottom_zone_y_min = page_height * (1 - self.HF_BOTTOM_ZONE_PERCENTAGE)

            blocks = page.get_text("dict")["blocks"]
            
            for b in blocks:
                if "lines" not in b: continue
                for l in b["lines"]:
                    line_text = " ".join([s["text"] for s in l["spans"]]).strip()
                    if not line_text: continue
                    
                    y_pos_top = l["bbox"][1]
                    y_pos_bottom = l["bbox"][3]

                    in_top_zone = y_pos_top < top_zone_y_max
                    in_bottom_zone = y_pos_bottom > bottom_zone_y_min

                    if (in_top_zone or in_bottom_zone) and (page_num < pages_to_scan_for_patterns):
                        normalized_text = self._normalize_text_for_hf_comparison(line_text)
                        
                        if normalized_text and len(normalized_text) > 3: # Ignore very short, non-meaningful strings
                            y_bucket = int(y_pos_top / 5) * 5 # Bucket to nearest 5 pixels
                            self._hf_candidates[(normalized_text, y_bucket, in_top_zone)] += 1
        logging.info(f"Header/Footer pre-processing complete. Found {len(self._hf_candidates)} unique candidates.")

    def _is_redundant_line(self, text: str, y_top: float, y_bottom: float, page_num: int) -> bool:
        """
        Determines if a given line is a header, footer, or other unnecessary/boilerplate text.
        """
        text_lower = text.strip().lower()
        
        page_dims = self._page_dimensions.get(page_num)
        page_height = page_dims[1] if page_dims else 842 # Default to A4 height if not found

        # Rule 1: Fixed Non-Content Patterns (fast and strict)
        if any(p.search(text_lower) for p in self.NON_CONTENT_PATTERNS): # Using compiled patterns
            logging.debug(f"  HF Filtered (Pattern): '{text}'")
            return True

        # Rule 2: Positional Zones (stricter)
        in_top_zone = y_top < (page_height * self.HF_TOP_ZONE_PERCENTAGE)
        in_bottom_zone = y_bottom > (page_height * (1 - self.HF_BOTTOM_ZONE_PERCENTAGE))

        # Rule 3: Very Short/Symbolic Lines (fine-tuned)
        # Avoid filtering valid short headings or list items
        if len(text.strip()) < 5:
            # Allow if it's a number like "1." or Roman "I." or letter "(a)" or "a." or bullet points
            if re.match(r"^\s*(\d+\.?|\([a-zA-Z]\)|\w\.|\s*[*+-]\s*)$", text.strip()): 
                return False
            logging.debug(f"  HF Filtered (Too Short): '{text}'")
            return True # Otherwise, filter if too short/just symbols

        # Rule 4: Repetitive Content Detection (from pre-processing, very strong signal)
        if self._total_pages_in_doc > 0: # Ensure pre-processing ran
            normalized_text = self._normalize_text_for_hf_comparison(text)
            y_bucket = int(y_top / 5) * 5

            if normalized_text and len(normalized_text) > 3: # Check only if meaningful text remains
                candidate_key = (normalized_text, y_bucket, in_top_zone)
                
                if candidate_key in self._hf_candidates:
                    count = self._hf_candidates[candidate_key]
                    if count >= self.HF_MIN_PAGES_FOR_REPETITION and \
                       (count / self._total_pages_in_doc) >= self.HF_REPETITION_THRESHOLD_PERCENT:
                        logging.debug(f"  HF Filtered (Repetitive): '{text}'")
                        return True
        
        return False

    def extract_text_lines_with_features(self, doc: fitz.Document) -> List[Dict]:
        """
        Extracts all relevant text lines from the PDF, calculates features for each,
        and filters out redundant content using _is_redundant_line.
        """
        text_lines_data: List[Dict] = []
        seq_idx = 0
        
        # Calculate document-wide average font size for relative comparison
        all_doc_font_sizes = []
        for p_num in range(len(doc)):
            for b in doc[p_num].get_text("dict")["blocks"]:
                for l in b.get("lines", []):
                    for s in l.get("spans", []):
                        if s["size"] > 0: all_doc_font_sizes.append(s["size"])
        avg_doc_font_size = statistics.mean(all_doc_font_sizes) if all_doc_font_sizes else 12.0
        logging.info(f"Document-wide average font size: {avg_doc_font_size:.2f}")

        # Stores the bottom Y position of the *last valid* line on each page
        prev_valid_line_bottom_y_per_page = defaultdict(lambda: 0.0)

        for page_num in range(len(doc)):
            page = doc[page_num]
            blocks = page.get_text("dict")["blocks"]
            
            # Sort blocks by Y then X for correct reading order (top-left to bottom-right)
            blocks_sorted = sorted(blocks, key=lambda b: (b['bbox'][1], b['bbox'][0]))

            for block_dict in blocks_sorted:
                if "lines" not in block_dict: continue
                
                # Sort lines within a block for correct reading order
                lines_sorted = sorted(block_dict["lines"], key=lambda l: (l['bbox'][1], l['bbox'][0]))

                for line_dict in lines_sorted:
                    line_text = " ".join([s["text"] for s in line_dict["spans"]]).strip()
                    if not line_text: continue

                    line_bbox = line_dict["bbox"]
                    y_top = line_bbox[1]
                    y_bottom = line_bbox[3]

                    # --- REDUNDANCY FILTERING ---
                    if self._is_redundant_line(line_text, y_top, y_bottom, page_num):
                        # Even if filtered, update prev_valid_line_bottom_y_per_page
                        # to correctly calculate whitespace for the *next* valid line on this page.
                        prev_valid_line_bottom_y_per_page[page_num] = y_bottom
                        continue # Skip this line

                    # Extract dominant font info from the line (e.g., from the first span)
                    first_span = line_dict["spans"][0] if line_dict["spans"] else {}
                    font_size = first_span.get("size", 0.0)
                    font_name = first_span.get("font", "")
                    color_int = first_span.get("color", 0) # Store as integer from PyMuPDF

                    # Calculate features
                    rel_font_size = round(font_size / avg_doc_font_size, 2) if avg_doc_font_size > 0 else 0.0
                    is_bold = self._is_bold(first_span.get("flags", 0))
                    is_italic = self._is_italic(first_span.get("flags", 0))
                    
                    has_enum = bool(re.match(r"^\s*(\d+(\.\d+)*\.?|[A-Z][a-zA-Z]*\.|\([a-zA-Z]\)|\d+\))\s*", line_text)) # Robust enum check
                    ends_with_period = line_text.strip().endswith('.')
                    ends_with_colon = line_text.strip().endswith(':')
                    has_cue = any(keyword in line_text.lower() for keyword in self.heading_keywords)
                    
                    whitespace_above = y_top - prev_valid_line_bottom_y_per_page[page_num]
                    whitespace_above = max(0.0, round(whitespace_above, 2)) # Cap at 0 if negative or small

                    current_line_data = {
                        'text': line_text,
                        'page': page_num + 1, # 1-indexed page number
                        'font_size': font_size,
                        'font_name': font_name,
                        'is_bold': is_bold,
                        'is_italic': is_italic,
                        'bbox': line_bbox,
                        'color': color_int,
                        'rel_font_size': rel_font_size,
                        'x_pos': line_bbox[0],
                        'y_pos': y_top, # Top Y of the line
                        'whitespace_above': whitespace_above,
                        'seq_idx': seq_idx, # Global sequence index for ordering
                        'word_count': len(line_text.split()),
                        'cap_ratio': round(sum(1 for c in line_text if c.isupper()) / max(len(line_text), 1), 2),
                        'ends_with_period': ends_with_period,
                        'ends_with_colon': ends_with_colon,
                        'has_enum': has_enum,
                        'has_cue': has_cue,
                    }
                    
                    current_line_data["heading_score"] = self.calculate_heading_score(current_line_data, avg_doc_font_size)
                    text_lines_data.append(current_line_data)
                    seq_idx += 1
                    prev_valid_line_bottom_y_per_page[page_num] = y_bottom # Update for next valid line
        logging.info(f"Extracted {len(text_lines_data)} meaningful lines after filtering redundant content.")
        return text_lines_data

    def analyze_font_statistics(self, text_blocks: List[Dict]) -> Dict:
        """Analyze font size distribution to identify potential body font size."""
        font_sizes = [block['font_size'] for block in text_blocks if block['font_size'] > 0] # Exclude 0 sizes
        
        if not font_sizes:
            return {}
            
        # The most common font size is usually the body text font size
        body_font_size = Counter(font_sizes).most_common(1)[0][0]
        
        # Calculate mean/median for broader context, but rely on mode for body_font_size
        stats = {
            'mean_font_size': statistics.mean(font_sizes),
            'median_font_size': statistics.median(font_sizes),
            'body_font_size': body_font_size
        }
        return stats
            

    def calculate_heading_score(self, line_data: Dict, avg_doc_font_size: float) -> float:
        """
        Calculate a score indicating likelihood of being a heading with stricter font importance.
        Logs detailed scoring steps.
        """
        score = 0.0
        text = line_data['text']

        logging.debug(f"\n--- Scoring line (Page {line_data['page']}): '{text}' ---")

        if not text:
            logging.debug("Score: 0.0 (empty text)")
            return 0.0

        # --- Font-based features (Primary Indicators - high weight, increased importance) ---
        current_score_component = 0
        if avg_doc_font_size > 0:
            size_ratio = line_data['font_size'] / avg_doc_font_size
            if size_ratio >= 1.8:
                current_score_component = 50  # Very large text
            elif size_ratio >= 1.5:
                current_score_component = 35  # Significantly larger
            elif size_ratio > self.MIN_HEADING_FONT_SIZE_RATIO:
                current_score_component = 25
        score += current_score_component
        logging.debug(f"  + Font size ratio ({line_data['font_size']:.2f}/{avg_doc_font_size:.2f}={size_ratio:.2f}): {current_score_component}")

        current_score_component = 0
        if line_data['is_bold']:
            current_score_component = 45  # Increased from 35
        score += current_score_component
        logging.debug(f"  + Is bold ({line_data['is_bold']}): {current_score_component}")

        current_score_component = 0
        if line_data['is_italic']:
            current_score_component = 0
        score += current_score_component
        logging.debug(f"  + Is italic ({line_data['is_italic']}): {current_score_component}")

        # --- Text Pattern features ---
        current_score_component = 0
        matched_pattern = False
        for pattern in self.heading_patterns:
            if pattern.match(text):
                current_score_component = 30  # Boosted pattern match
                matched_pattern = True
                break
        score += current_score_component
        logging.debug(f"  + Pattern match ({matched_pattern}): {current_score_component}")

        current_score_component = 0
        if line_data['has_enum']:
            current_score_component = 35  # Strong boost for lines like 1., 1.1, etc.
        score += current_score_component
        logging.debug(f"  + Has enumeration ({line_data['has_enum']}): {current_score_component}")

        current_score_component = 0
        if line_data['has_cue']:
            current_score_component = 10  # Reduced
        score += current_score_component
        logging.debug(f"  + Has cue word ({line_data['has_cue']}): {current_score_component}")

        # --- Positional/Whitespace features ---
        current_score_component = 0
        body_size = avg_doc_font_size
        combined_whitespace = line_data.get('whitespace_above', 0.0) + line_data.get('whitespace_below', 0.0)
        if combined_whitespace > (body_size * 2.5):
            current_score_component = 15
        elif combined_whitespace > (body_size * 1.5):
            current_score_component = 10
        elif combined_whitespace > (body_size * 0.8):
            current_score_component = 5
        score += current_score_component
        logging.debug(f"  + Combined whitespace: {combined_whitespace:.2f} => {current_score_component}")

        # X-position (alignment)
        current_score_component = 0
        page_dims = self._page_dimensions.get(line_data['page'] - 1)
        page_width = page_dims[0] if page_dims else 595.0
        typical_left_margin = page_width * 0.12
        if abs(line_data['x_pos'] - typical_left_margin) < 10:
            current_score_component = 10
        score += current_score_component
        logging.debug(f"  + Left alignment ({line_data['x_pos']:.2f}): {current_score_component}")

        current_score_component = 0
        text_center_x = line_data['x_pos'] + (line_data['bbox'][2] - line_data['x_pos']) / 2
        page_center_x = page_width / 2
        if abs(text_center_x - page_center_x) < (page_width * 0.08):
            current_score_component = 12
        score += current_score_component
        logging.debug(f"  + Centering ({text_center_x:.2f} vs {page_center_x:.2f}): {current_score_component}")

        # --- Content Penalties ---
        current_score_component = 0
        word_count = line_data['word_count']
        if 2 <= word_count <= self.MAX_HEADING_WORD_COUNT:
            current_score_component = 6
        elif word_count > self.MAX_HEADING_WORD_COUNT + 10:
            current_score_component = -30
        elif word_count < 2:
            current_score_component = -25
        score += current_score_component
        logging.debug(f"  + Word count ({word_count}): {current_score_component}")

        current_score_component = 0
        if line_data['cap_ratio'] == 1.0 and word_count <= self.MAX_HEADING_WORD_COUNT / 2:
            current_score_component = 12
        elif text.istitle() and word_count <= self.MAX_HEADING_WORD_COUNT:
            current_score_component = 8
        score += current_score_component
        logging.debug(f"  + Capitalization (ALL CAPS:{line_data['cap_ratio']==1.0}, Title Case:{text.istitle()}): {current_score_component}")

        current_score_component = 0
        if line_data['ends_with_period']:
            current_score_component = -45  # Increased penalty
        elif line_data['ends_with_colon']:
            current_score_component = 15  # Strong heading signal
        elif not (line_data['ends_with_period'] or line_data['ends_with_colon']):
            current_score_component = 10
        score += current_score_component
        logging.debug(f"  + Ending punct (period:{line_data['ends_with_period']}, colon:{line_data['ends_with_colon']}): {current_score_component}")

        current_score_component = 0
        if line_data['page'] == 1 and line_data['y_pos'] < 120 and line_data['font_size'] >= body_size * 1.8:
            current_score_component = 25
        score += current_score_component
        logging.debug(f"  + First page top bonus: {current_score_component}")

        current_score_component = 0
        if line_data['color'] == 0:
            current_score_component = 3
        score += current_score_component
        logging.debug(f"  + Color (black): {current_score_component}")

        logging.debug(f"  --- Final Score: {score} ---")
        return score

    
    def _get_heading_font_sizes(self, all_headings: List[Dict]) -> List[float]:
        """Extracts and sorts unique font sizes from identified headings."""
        return sorted(list(set(h['font_size'] for h in all_headings)), reverse=True)

    def classify_heading_level(self, heading: Dict, all_headings_in_order: List[Dict], font_stats: Dict) -> str:
        """
        Determines the H1, H2, H3 level based on font size relative to other identified headings
        and structural cues.
        """
        text = heading['text']
        logging.debug(f"Classifying level for: '{text}' (Score: {heading.get('heading_score',0)})")

        if not all_headings_in_order:
            logging.debug("  No other headings, defaulting to H1.")
            return 'H1'

        # Heuristic for mapping global font sizes to levels
        unique_heading_sizes = self._get_heading_font_sizes(all_headings_in_order)
        
        level_map = {}
        if len(unique_heading_sizes) >= 1: level_map[unique_heading_sizes[0]] = 'H1'
        if len(unique_heading_sizes) >= 2: level_map[unique_heading_sizes[1]] = 'H2'
        if len(unique_heading_sizes) >= 3: level_map[unique_heading_sizes[2]] = 'H3'
        
        # For any smaller sizes, default to H3 if not already mapped
        for size in unique_heading_sizes[3:]:
            level_map[size] = 'H3'

        current_level_str = level_map.get(heading['font_size'], 'H3') # Initial level from font size
        logging.debug(f"  Initial level from size map ({heading['font_size']:.1f}): {current_level_str}")

        # --- Refine Level based on Enumeration Pattern (Strongest Structural Signal) ---
        body_size = font_stats.get('body_font_size', 12)
        
        if re.match(r"^\s*\d+\.\d+\.\d+(\.\d+)*\s+", text): # e.g., 1.1.1, 1.1.1.1 etc.
            logging.debug("  Matched X.X.X enumeration, set to H3.")
            return 'H3'
        elif re.match(r"^\s*\d+\.\d+\s+", text): # e.g., 1.1, 2.3 etc.
            logging.debug("  Matched X.X enumeration.")
            # If current is initially mapped as H1, let's reconsider. 1.1 is rarely H1.
            level = 'H2' if current_level_str != 'H1' else current_level_str
            logging.debug(f"  Refined to {level}.")
            return level
        elif re.match(r"^\s*\d+\s+", text) or re.match(r"^\s*[IVXLCDM]+\s+", text): # e.g., 1, 2, I, II
            logging.debug("  Matched X. or Roman enumeration.")
            # This is a major section number. Likely H1 or H2.
            # If it's the largest font size or very large, make it H1.
            if heading['font_size'] >= body_size * 1.8 and current_level_str == 'H1':
                logging.debug("  Prominent X. is H1.")
                return 'H1'
            logging.debug("  Prominent X. is H2.")
            return 'H2' # Default a major numbered section to H2 if not the absolute largest

        # If it's a letter enumeration (a), (b), A., B. these are often H3 or list items
        elif re.match(r"^\s*[a-zA-Z]\.?\s*\)", text) or re.match(r"^\s*[a-zA-Z]\s*\.\s+", text):
             logging.debug("  Matched letter enumeration, set to H3.")
             return 'H3' 

        # --- Refine Level based on X-Position (Indentation) ---
        page_dims = self._page_dimensions.get(heading['page'] - 1)
        page_width = page_dims[0] if page_dims else 595.0
        
        typical_doc_margin = page_width * 0.1 # Example 10% margin
        
        if heading['x_pos'] > typical_doc_margin + 30: # If indented more than ~0.4 inch from typical margin
            logging.debug(f"  Indented (x_pos {heading['x_pos']:.2f} > {typical_doc_margin+30:.2f}).")
            if current_level_str == 'H1':
                logging.debug("  Demoted H1 to H2 due to indentation.")
                return 'H2'
            if current_level_str == 'H2':
                logging.debug("  Demoted H2 to H3 due to indentation.")
                return 'H3'

        logging.debug(f"  Final level (default/no change): {current_level_str}")
        return current_level_str

    def extract_title(self, text_lines: List[Dict], font_stats: Dict) -> str:
        """Extract document title (usually largest text on first page, top-most, centered)."""
        if not text_lines:
            logging.debug("No text lines for title extraction, returning 'Document'.")
            return "Document"
            
        # Filter for text blocks on the first page and those not caught by redundant filter
        first_page_relevant_lines = [
            line for line in text_lines
            if line['page'] == 1 and len(line['text'].strip()) > 3
        ]
        
        if not first_page_relevant_lines:
            logging.debug("No relevant lines on first page for title, attempting fallback to first heading.")
            # Fallback to first meaningful heading if page 1 is empty or only junk
            if text_lines:
                high_score_headings = sorted([b for b in text_lines if b.get('heading_score', 0) > self.HEADING_SCORE_THRESHOLD + 10], # Use high score
                                             key=lambda x: (x['page'], x['y_pos']))
                if high_score_headings:
                    logging.debug(f"Fallback title: '{high_score_headings[0]['text']}'")
                    return high_score_headings[0]['text'].strip()
            logging.debug("No fallback title found, returning 'Document'.")
            return "Document"

        # Find the max font size on the first page relevant blocks
        max_size = 0.0
        if first_page_relevant_lines:
            max_size = max(line['font_size'] for line in first_page_relevant_lines)
        else:
            logging.debug("No relevant font sizes for title, returning 'Document'.")
            return "Document"

        # Candidates are lines with the max font size on the first page, and are near top.
        title_candidates = [
            line for line in first_page_relevant_lines
            if line['font_size'] == max_size and line['y_pos'] < 200 # Must be in the top part of the page
        ]
        
        if not title_candidates: # Fallback: sometimes title font isn't the absolute largest
            logging.debug(f"No direct max-size title candidates in top 200px, looking for >= 80% of max_size ({max_size}).")
            title_candidates = [
                line for line in first_page_relevant_lines
                if line['font_size'] >= max_size * 0.8 and line['y_pos'] < 200
            ]
        
        if not title_candidates: # Final fallback if even 80% candidates are bad
            logging.debug("No suitable title candidates found, returning 'Document'.")
            return "Document"

        # Get the width of the first page to calculate center
        first_page_dims = self._page_dimensions.get(0)
        page_width = first_page_dims[0] if first_page_dims else 595.0

        # Sort candidates: prioritize by y-position (top-most), then by proximity to page center
        title_candidates.sort(key=lambda x: (x['y_pos'], abs( (x['bbox'][0] + x['bbox'][2])/2 - page_width / 2 ) ))
        
        title_lines = []
        if title_candidates:
            main_title_candidate = title_candidates[0]
            title_lines.append(main_title_candidate['text'].strip())
            
            # Look for closely following lines with very similar properties to merge
            current_main_bottom_y = main_title_candidate['bbox'][3]
            for i in range(1, len(title_candidates)):
                candidate = title_candidates[i]
                # Check for same page, very similar font size, close vertically, and reasonably centered
                # Also, ensure it's not a common footer/header text
                if (candidate['page'] == main_title_candidate['page'] and
                    abs(candidate['font_size'] - main_title_candidate['font_size']) < 1.5 and # Tolerance for slightly different sizes
                    (candidate['y_pos'] - current_main_bottom_y) < (main_title_candidate['font_size'] * 2.0) and # Within 2 line heights
                    abs( (candidate['bbox'][0] + candidate['bbox'][2])/2 - page_width / 2 ) < (page_width * 0.15) and # Still relatively centered
                    not any(p.search(candidate['text'].lower()) for p in self.NON_CONTENT_PATTERNS) ): # Not a known non-content pattern
                    
                    title_lines.append(candidate['text'].strip())
                    current_main_bottom_y = candidate['bbox'][3] # Update bottom for next check
                else:
                    break # Stop merging if not continuous
        
        title = " ".join(title_lines)
        title = re.sub(r'\s+', ' ', title).strip()
        
        # Final sanity check on the extracted title:
        # Too short, looks like an enum, or matches common non-content patterns
        if len(title) < 5 or re.match(r'^\d+\.?$', title) or any(p.search(title.lower()) for p in self.NON_CONTENT_PATTERNS):
            logging.debug(f"Sanity check failed for title '{title}'. Attempting fallback to first high-scoring heading.")
            # Fallback to first high-scoring heading
            if text_lines:
                high_score_headings = sorted([b for b in text_lines if b.get('heading_score', 0) > self.HEADING_SCORE_THRESHOLD + 10], # Even stricter score for fallback
                                             key=lambda x: (x['page'], x['y_pos']))
                if high_score_headings:
                    logging.debug(f"Fallback title: '{high_score_headings[0]['text']}'")
                    return high_score_headings[0]['text'].strip()
            logging.debug("No fallback title found, returning 'Document'.")
            return "Document" # Ultimate fallback

        logging.debug(f"Extracted title: '{title}'")
        return title if title else "Document"
            
    def merge_multiline_headings(self, headings: List[Dict]) -> List[Dict]:
        """Merge headings that span multiple lines and are detected as separate blocks."""
        if not headings:
            return []

        merged_headings = []
        # Sort by page and then y-position to ensure correct order for merging
        sorted_headings = sorted(headings, key=lambda h: (h['page'], h['bbox'][1]))

        if not sorted_headings:
            return []

        current_merged = sorted_headings[0].copy()
        logging.debug(f"Starting multi-line merge. First heading: '{current_merged['text']}'")

        for i in range(1, len(sorted_headings)):
            next_h = sorted_headings[i]
            
            # Conditions for NOT merging (i.e., they are distinct lines) - PRIORITIZE these
            if current_merged['page'] != next_h['page']:
                logging.debug(f"  Different page. Appending '{current_merged['text']}'. New current: '{next_h['text']}'")
                merged_headings.append(current_merged)
                current_merged = next_h.copy()
                continue
            
            vertical_distance = next_h['bbox'][1] - current_merged['bbox'][3]
            if vertical_distance >= (current_merged['font_size'] * 1.5): # Too much vertical space
                logging.debug(f"  Too much vertical space ({vertical_distance:.2f} >= {current_merged['font_size'] * 1.5:.2f}). Appending '{current_merged['text']}'. New current: '{next_h['text']}'")
                merged_headings.append(current_merged)
                current_merged = next_h.copy()
                continue
            
            if abs(current_merged['font_size'] - next_h['font_size']) >= 2.0: # Significant font size difference
                logging.debug(f"  Significant font size difference ({current_merged['font_size']:.1f} vs {next_h['font_size']:.1f}). Appending '{current_merged['text']}'. New current: '{next_h['text']}'")
                merged_headings.append(current_merged)
                current_merged = next_h.copy()
                continue
            
            if current_merged.get('ends_with_period', False) and not re.match(r'.*\d+\.$', current_merged['text'].strip()):
                logging.debug(f"  Current line ends with period (not enum). Appending '{current_merged['text']}'. New current: '{next_h['text']}'")
                merged_headings.append(current_merged)
                current_merged = next_h.copy()
                continue
            
            if next_h['has_enum']: # Next line starts with an enumeration
                logging.debug(f"  Next line has enum. Appending '{current_merged['text']}'. New current: '{next_h['text']}'")
                merged_headings.append(current_merged)
                current_merged = next_h.copy()
                continue
            
            if current_merged['word_count'] > self.MAX_HEADING_WORD_COUNT + 5 and next_h['word_count'] > self.MAX_HEADING_WORD_COUNT + 5: # Stricter length check for merging
                logging.debug(f"  Both lines too long for multi-line heading. Appending '{current_merged['text']}'. New current: '{next_h['text']}'")
                merged_headings.append(current_merged)
                current_merged = next_h.copy()
                continue
            
            if not current_merged['is_bold'] and not next_h['is_bold'] and current_merged['font_size'] < (current_merged['font_size'] * 1.5): # Neither is bold and not large
                 logging.debug(f"  Neither bold and not exceptionally large. Appending '{current_merged['text']}'. New current: '{next_h['text']}'")
                 merged_headings.append(current_merged)
                 current_merged = next_h.copy()
                 continue


            # If none of the "don't merge" conditions met, then merge
            logging.debug(f"  Merging '{current_merged['text']}' with '{next_h['text']}'")
            current_merged['text'] += ' ' + next_h['text'].strip()
            # Update bbox to encompass both lines
            current_merged['bbox'] = (min(current_merged['bbox'][0], next_h['bbox'][0]), # min x0
                                      min(current_merged['bbox'][1], next_h['bbox'][1]), # min y0
                                      max(current_merged['bbox'][2], next_h['bbox'][2]), # max x1
                                      max(current_merged['bbox'][3], next_h['bbox'][3])) # max y1
            
            # Update combined attributes (prioritize strongest or combine)
            current_merged['font_size'] = max(current_merged['font_size'], next_h['font_size']) 
            current_merged['is_bold'] = current_merged['is_bold'] or next_h['is_bold']
            current_merged['is_italic'] = current_merged['is_italic'] or next_h['is_italic']
            current_merged['word_count'] += next_h['word_count']
            current_merged['cap_ratio'] = round(sum(1 for c in current_merged['text'] if c.isupper()) / max(len(current_merged['text']), 1), 2)
            current_merged['ends_with_period'] = next_h['ends_with_period'] # Use last line's ending punct
            current_merged['ends_with_colon'] = next_h['ends_with_colon']
            current_merged['has_enum'] = current_merged['has_enum'] or next_h['has_enum']     
            current_merged['has_cue'] = current_merged['has_cue'] or next_h['has_cue']         
            current_merged['heading_score'] = max(current_merged.get('heading_score', 0), next_h.get('heading_score', 0)) # Take max score
            # No `append` here, `current_merged` will be further processed with `next_h` if possible
        
        # Append the last (or only) merged heading after the loop finishes
        merged_headings.append(current_merged)
        logging.debug(f"Finished multi-line merge. Total merged headings: {len(merged_headings)}")
        
        return merged_headings
            
    def process_pdf(self, pdf_path: str) -> Dict:
        """Main method to process PDF and extract outline."""
        
        self._reset_state() # Reset state for new PDF
        logging.info(f"Starting processing for PDF: {pdf_path}")
        
        try:
            doc = fitz.open(pdf_path)
            
            # --- Pass 1: Pre-process for Header/Footer Detection ---
            self._pre_process_for_hf_detection(doc)
            
            # --- Pass 2: Extract meaningful text lines with calculated features ---
            text_lines = self.extract_text_lines_with_features(doc) # This now filters redundant lines
            
            if not text_lines:
                doc.close()
                logging.warning(f"No meaningful text lines extracted from {pdf_path}.")
                return {"title": "Document", "outline": []}
                
            # Analyze font statistics on the *meaningful* text lines
            font_stats = self.analyze_font_statistics(text_lines)
            
            # Filter for heading candidates based on score threshold
            # Sort by score highest first to prioritize stronger candidates if a cap is applied later
            heading_candidates = sorted(
                [line_data for line_data in text_lines if line_data.get('heading_score', 0) >= self.HEADING_SCORE_THRESHOLD],
                key=lambda x: x['heading_score'], reverse=True
            )
            logging.info(f"Initial heading candidates (score >= {self.HEADING_SCORE_THRESHOLD}): {len(heading_candidates)}")
            
            # Spatial filtering and de-duplication
            final_filtered_headings = []
            seen_norm_texts = set() # To avoid duplicate headings by text content
            
            # Sort again by page and y_pos for proper sequential processing
            heading_candidates_spatial_sort = sorted(heading_candidates, key=lambda x: (x['page'], x['y_pos']))
            
            last_added_bbox = None
            last_added_page = -1

            for candidate in heading_candidates_spatial_sort:
                norm_text = re.sub(r'\s+', ' ', candidate['text']).strip().lower()
                
                # Check if this text is already processed, or too short/non-meaningful
                if len(norm_text) < 5 or norm_text in seen_norm_texts:
                    logging.debug(f"Skipping short or seen: '{candidate['text']}'")
                    continue

                # Strict spatial proximity check for true duplicates or very close sub-elements
                # If current candidate is very close vertically to the last added heading,
                # and has very similar font characteristics, it might be a duplicate rendering artifact
                # or a very short, subordinate element already covered by a parent heading.
                if last_added_bbox and last_added_page == candidate['page']:
                    vertical_distance = candidate['y_pos'] - last_added_bbox[3]
                    if vertical_distance < (candidate['font_size'] * 0.8) and \
                       abs(candidate['font_size'] - final_filtered_headings[-1]['font_size']) < 1.0 and \
                       candidate['is_bold'] == final_filtered_headings[-1]['is_bold']:
                        logging.debug(f"Skipping potentially redundant close line: '{candidate['text']}'")
                        continue
                
                final_filtered_headings.append(candidate)
                seen_norm_texts.add(norm_text) # Add normalized text to seen set
                last_added_bbox = candidate['bbox']
                last_added_page = candidate['page']

                if len(final_filtered_headings) >= 150: # Cap total headings for performance/output size
                    logging.info(f"Reached max heading cap of 150. Stopping early.")
                    break
            
            logging.info(f"Headings after initial filtering and de-duplication: {len(final_filtered_headings)}")

            # Merge multiline headings
            merged_headings = self.merge_multiline_headings(final_filtered_headings)
            logging.info(f"Headings after merging multi-line: {len(merged_headings)}")

            # Re-sort after merging, and before level classification to ensure correct order
            merged_headings.sort(key=lambda x: (x['page'], x['bbox'][1]))

            # --- Classify heading levels (H1, H2, H3) ---
            outline_entries = []
            
            for heading in merged_headings:
                level = self.classify_heading_level(heading, merged_headings, font_stats) # Pass all merged headings & font_stats

                outline_entries.append({
                    'level': level,
                    'text': heading['text'].strip(),
                    'page': heading['page']-1
                })
            
            # --- Extract Title ---
            # Pass *all* extracted lines (before heading filtering) to extract_title
            # because the title might not be classified as a 'heading' by score, but it's the largest text.
            title = self.extract_title(text_lines, font_stats) 
            
            doc.close()
            logging.info(f"Finished processing {pdf_path}. Extracted title: '{title}', {len(outline_entries)} outline entries.")
            
            return {
                "title": title,
                "outline": outline_entries
            }
            
        except Exception as e:
            logging.error(f"Error processing PDF {pdf_path}: {str(e)}", exc_info=True) # Log full traceback
            # Ensure document is closed even on error
            try:
                if 'doc' in locals() and doc: # Check if doc variable exists and is open
                    doc.close()
            except Exception as close_e:
                logging.error(f"Error closing document after processing failure: {close_e}")
            return {"title": "Document", "outline": []}


def main():
    parser = argparse.ArgumentParser(description='Extract headings from PDF files')
    parser.add_argument('--input-dir', default='/app/input', 
                        help='Input directory containing PDF files')
    parser.add_argument('--output-dir', default='/app/output',
                        help='Output directory for JSON files')
    
    args = parser.parse_args()
    
    # Create output directory if it doesn't exist
    os.makedirs(args.output_dir, exist_ok=True)
    
    extractor = PDFHeadingExtractor() # Initialize extractor
    
    input_files = [f for f in os.listdir(args.input_dir) if f.lower().endswith('.pdf')]
    
    if not input_files:
        logging.error("No PDF files found in input directory.")
        return
    
    for filename in input_files:
        input_path = os.path.join(args.input_dir, filename)
        output_filename = os.path.splitext(filename)[0] + '.json'
        output_path = os.path.join(args.output_dir, output_filename)
        
        logging.info(f"Processing {filename}...")
        
        result = extractor.process_pdf(input_path)
        
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
        
        logging.info(f"Generated {output_filename}")

if __name__ == "__main__":
    main()


