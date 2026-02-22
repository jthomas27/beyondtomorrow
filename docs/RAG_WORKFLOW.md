# RAG Workflow Summary

**RAG (Retrieval-Augmented Generation)** is a technique that helps AI give better answers by retrieving relevant information from your own documents before generating a response.

---

## Workflow Overview

```
[Documents] → [Preprocessing] → [Chunking] → [Embeddings] → [Vector Database] → [AI Retrieval]
```


---

## Step 1: Store Knowledge Documents
AI knowledge documents will be stored in Railway as stored objects. These documents contain the information you want the to reference in your prompt to add context to the AI response. For example,
- Product manuals
- FAQs
- Research notes
- Company policies

---

## Step 1.5: Document Preprocessing – Preparing Your Data

Before documents can be chunked and embedded, they must be **preprocessed**—extracted from their original format, cleaned, and standardized. This step ensures the AI receives high-quality, consistent text to work with. Clean, standardized text produces better embeddings and more accurate retrieval.

---

### Document Preprocesing ###
### Part 1: Extracting Data from Different File Types

Different document types require different extraction methods:

| File Type | What's Inside | Extraction Challenge |
|-----------|---------------|---------------------|
| **Plain Text (.txt)** | Raw text | Easiest—just read the file |
| **PDF** | Text, images, tables, layouts | Complex; text may be in layers, images, or scanned |
| **Word (.docx)** | Formatted text, styles, tables | Need to parse XML structure inside the file |
| **Excel (.xlsx, .csv)** | Tabular data in rows/columns | Must decide how to represent tables as text |
| **HTML/Web Pages** | Text mixed with code and styling | Need to strip HTML tags and navigation elements |
| **PowerPoint (.pptx)** | Slides with text, images, notes | Text scattered across slides and speaker notes |
| **Emails (.eml, .msg)** | Headers, body, attachments | Must extract body and handle attachments separately |
| **Images (scanned docs)** | No text—just pixels | Requires OCR (Optical Character Recognition) |
| **Markdown (.md)** | Text with simple formatting | Relatively easy; decide whether to keep formatting |

#### Recommended Python Packages for Extraction

| Package | Best For | Description |
|---------|----------|-------------|
| **Unstructured** | Most file types | All-in-one library that handles PDFs, Word, HTML, images, and more. Recommended for most projects. |
| **PyMuPDF (fitz)** | PDFs | Fast, accurate PDF text extraction with layout preservation |
| **pdfplumber** | PDFs with tables | Excellent for extracting tables from PDFs |
| **python-docx** | Word documents | Read and extract text from .docx files |
| **BeautifulSoup** | HTML/Web pages | Parse and extract text from web pages |
| **pandas** | CSV/Excel | Read tabular data and convert to text |
| **python-pptx** | PowerPoint | Extract text from slides and notes |
| **pytesseract** | Scanned images | OCR to convert images to text |
| **Textract (AWS)** | Complex documents | Cloud service for enterprise document extraction |

#### Extraction Services and APIs

| Service | Description |
|---------|-------------|
| **Unstructured.io API** | Hosted version of Unstructured library; handles complex documents automatically |
| **Azure AI Document Intelligence** | Microsoft's document extraction with layout understanding |
| **Amazon Textract** | AWS service for extracting text and data from scanned documents |
| **Google Document AI** | Google's document processing with pre-trained models |
| **LlamaParse** | Specialized for parsing documents for RAG applications |

---

### Part 2: Cleaning the Extracted Text

Once text is extracted, it often contains "noise" that should be removed:

| Noise Type | Example | Why Remove It |
|------------|---------|---------------|
| **Headers/Footers** | "Page 1 of 50", "Company Confidential" | Repeated on every page; adds no value |
| **Page Numbers** | "- 42 -" | Irrelevant for understanding content |
| **Excessive Whitespace** | Multiple blank lines, tabs | Creates inconsistent chunking |
| **Special Characters** | "â€™" instead of apostrophe | Encoding errors that confuse AI |
| **Boilerplate Text** | "Copyright 2024 All Rights Reserved" | Legal text that clutters results |
| **Navigation Elements** | "Click here", "Back to top" | Web artifacts with no meaning |
| **Duplicate Content** | Same paragraph repeated | Wastes storage and skews search results |

#### Common Cleaning Steps

```
Raw Extracted Text                    Cleaned Text
─────────────────────                 ─────────────────────
"  Page 1 of 50\n\n\n                "The product features
Company Header\n                      automatic backup and
The product features                  cloud synchronization.
automatic   backup and                Users can access files
cloud synchronization.\n\n            from any device."
Users can access files
from    any device.\n
Footer - Confidential  "
```

#### Recommended Approach for Cleaning

1. **Remove headers, footers, and page numbers** – Use patterns or position-based rules
2. **Fix encoding issues** – Convert to UTF-8, replace broken characters
3. **Normalize whitespace** – Replace multiple spaces/newlines with single ones
4. **Remove boilerplate** – Strip repeated legal text, copyright notices
5. **Handle special cases** – URLs, email addresses, code blocks (keep or format consistently)

---

### Part 3: Normalization and Standardization

**Normalization** makes text consistent so the same information is always represented the same way.

| What to Normalize | Before | After | Why |
|-------------------|--------|-------|-----|
| **Case** | "APPLE", "Apple", "apple" | "apple" (or keep original) | Consistent matching |
| **Dates** | "Jan 5, 2024", "5/1/24", "2024-01-05" | "2024-01-05" | Standard format |
| **Numbers** | "one thousand", "1,000", "1000" | "1000" | Consistent representation |
| **Abbreviations** | "Dr.", "Doctor" | "Doctor" (or keep both) | Reduces ambiguity |
| **Unicode** | "café", "cafe\u0301" | "café" | Same visual = same text |
| **Contractions** | "don't", "do not" | Choose one style | Consistency |

#### Standardization Considerations

| Factor | Guidance |
|--------|----------|
| **Preserve Meaning** | Don't normalize so aggressively that you lose important distinctions |
| **Domain-Specific Terms** | Keep technical terms, product names, and acronyms intact |
| **Language** | Handle multilingual content appropriately |
| **Structure Markers** | Decide whether to keep or remove bullet points, numbering, headings |

---

### Part 4: Formatting for AI Consumption

The final step is formatting cleaned text so it's optimal for chunking and embedding:

| Formatting Decision | Options | Recommendation |
|--------------------|---------|----------------|
| **Keep Headings?** | Yes/No | Yes – they provide context for chunks |
| **Keep Lists?** | As bullets or convert to prose | Keep as bullets – preserves structure |
| **Handle Tables?** | Convert to text, keep as markdown, or separate | Convert to markdown tables or prose descriptions |
| **Code Blocks?** | Keep formatted or flatten | Keep formatted with language markers |
| **Links/URLs?** | Keep, remove, or convert to text | Keep the link text, optionally keep URL |

#### Recommended Output Format

For most RAG applications, output **clean Markdown**:
- Preserves headings (useful context for chunks)
- Tables render as readable text
- Lists stay structured
- Easy to read and process

---

### Recommended Preprocessing Pipeline

For most Python projects building an AI knowledge base, we recommend this approach:

```
┌─────────────────────────────────────────────────────────────┐
│                    RECOMMENDED PIPELINE                      │
└─────────────────────────────────────────────────────────────┘

Step 1: EXTRACTION
├── Primary Tool: Unstructured (handles most file types)
├── Alternative: LlamaParse (optimized for RAG)
└── For images/scans: pytesseract or cloud OCR

Step 2: CLEANING  
├── Primary Tool: Unstructured (includes cleaning)
├── Custom rules: Python regex for domain-specific noise
└── Encoding: ftfy library for fixing encoding issues

Step 3: NORMALIZATION
├── Text normalization: Python unicodedata library
├── Date/number standardization: Custom rules or dateutil
└── Keep domain terms intact

Step 4: OUTPUT FORMAT
├── Format: Clean Markdown
├── Include: Headings, lists, tables (as markdown)
└── Metadata: Attach source filename, date, type to each document
```

### Why Unstructured is Recommended

| Advantage | Description |
|-----------|-------------|
| **All-in-One** | Handles PDFs, Word, HTML, images, email, and more in one library |
| **Intelligent Extraction** | Understands document layout, not just raw text |
| **Built-in Cleaning** | Removes headers, footers, and common noise automatically |
| **RAG-Optimized** | Designed specifically for preparing documents for AI applications |
| **Open Source + API** | Use locally for free or use their hosted API for convenience |
| **Active Development** | Regularly updated with new features and file type support |

### Alternative: LlamaParse

For complex documents (especially PDFs with tables, charts, and complex layouts), **LlamaParse** from LlamaIndex is an excellent alternative:

| Advantage | Description |
|-----------|-------------|
| **RAG-First Design** | Built specifically for retrieval-augmented generation |
| **Handles Complex PDFs** | Excellent at tables, multi-column layouts, and embedded images |
| **Markdown Output** | Outputs clean markdown ready for chunking |
| **Cloud-Based** | No local dependencies to manage |

---

### Preprocessing Checklist

Before moving to chunking, ensure your documents have been:

- [ ] **Extracted** – Text pulled from original file format
- [ ] **Cleaned** – Noise, headers, footers removed
- [ ] **Normalized** – Consistent encoding, whitespace, formatting
- [ ] **Formatted** – Structured as clean markdown or plain text
- [ ] **Validated** – Spot-check a few documents for quality
- [ ] **Metadata attached** – Source, date, and type recorded

➡️ **Next:** Break preprocessed documents into smaller pieces (chunking).

---

## Step 2: Chunking – Breaking Documents into Digestible Pieces

| Reason | Explanation |
|--------|-------------|
| **AI Token Limits** | Language models can only process a limited amount of text at once (e.g., 4,000-128,000 tokens depending on the model). Large documents must be split to fit these limits. |
| **Precise Retrieval** | Smaller chunks allow the AI to find the *exact* relevant section rather than retrieving an entire 50-page document. |
| **Better Embeddings** | Embeddings work best when they represent a focused topic. A single embedding for an entire book would lose important details. |
| **Cost Efficiency** | Processing smaller, targeted chunks reduces API costs and speeds up retrieval. |

### How Chunking Works

```
┌────────────────────────────────────────┐
│         Original Document              │
│  (50 pages of product documentation)   │
└───────────────────┬────────────────────┘
                    │
                    ▼
           ┌───────────────┐
           │   Chunking    │
           │   Process     │
           └───────┬───────┘
                   │
     ┌─────────────┼─────────────┐
     │             │             │
     ▼             ▼             ▼
┌─────────┐  ┌─────────┐  ┌─────────┐
│ Chunk 1 │  │ Chunk 2 │  │ Chunk 3 │  ... (many chunks)
│ 500     │  │ 500     │  │ 500     │
│ tokens  │  │ tokens  │  │ tokens  │
└─────────┘  └─────────┘  └─────────┘
```

### Chunking Strategies

Different chunking methods suit different types of content:

| Strategy | How It Works | Best For |
|----------|--------------|----------|
| **Fixed-Size Chunking** | Splits text into chunks of equal character or token count (e.g., every 500 tokens) | Simple documents, general-purpose use |
| **Sentence-Based Chunking** | Splits at sentence boundaries to keep complete thoughts together | Articles, conversational content |
| **Paragraph-Based Chunking** | Uses paragraph breaks as natural splitting points | Well-structured documents with clear sections |
| **Semantic Chunking** | Uses AI to detect topic changes and splits when the subject shifts | Complex documents with flowing topics |
| **Recursive Chunking** | Tries multiple split strategies (paragraphs → sentences → characters) until chunks fit size limits | Mixed content types |
| **Document-Structure Chunking** | Respects headings, sections, and document hierarchy | Technical manuals, structured reports |

### What is Chunk Overlap?

**Overlap** means that consecutive chunks share some text at their boundaries. This prevents important information from being split awkwardly between two chunks.

```
Without Overlap:
[Chunk 1: "The error occurs when..."] [Chunk 2: "...the system restarts."]
→ Context is lost at the boundary

With Overlap (100 tokens):
[Chunk 1: "The error occurs when the system restarts. To fix..."]
[Chunk 2: "...the system restarts. To fix this issue, you should..."]
→ Both chunks contain the complete thought
```

**Recommendation:** Use 10-20% overlap (e.g., 100 tokens overlap for 500-token chunks).

### Chunking Considerations for AI Knowledge Bases

| Factor | Guidance |
|--------|----------|
| **Chunk Size** | Start with 500-1,000 tokens. Smaller = more precision; larger = more context. |
| **Overlap** | Use 10-20% overlap to preserve context at boundaries. |
| **Metadata** | Attach source info (filename, page number, section title) to each chunk for traceability. |
| **Content Type** | Match chunking strategy to your document type (code, prose, tables, etc.). |

### Popular Python Packages for Chunking

| Package | Description | Best For |
|---------|-------------|----------|
| **LangChain** | Comprehensive framework with multiple text splitters (recursive, character, token-based, markdown, HTML, code) | Most use cases; batteries-included solution |
| **LlamaIndex** | Provides intelligent node parsers that preserve document structure and relationships | Complex document hierarchies |
| **Unstructured** | Specializes in parsing and chunking diverse file formats (PDF, Word, HTML, images) | Mixed document types |
| **spaCy** | NLP library with sentence segmentation for sentence-based chunking | Linguistic accuracy |
| **NLTK** | Classic NLP toolkit with tokenizers and sentence splitters | Academic/research projects |
| **Tiktoken** | OpenAI's tokenizer for precise token counting (essential for staying within limits) | Token-accurate chunking |
| **Haystack** | End-to-end framework with document preprocessors and splitters | Production RAG pipelines |

---

## Step 3: Convert Chunks to Embeddings (Text Embedding Deep Dive)

| Reason | Explanation |
|--------|-------------|
| **Computers Can't Read** | Machines work with numbers, not words. Embeddings bridge this gap. |
| **Meaning Comparison** | Embeddings let us measure how similar two pieces of text are (e.g., "happy" and "joyful" have similar embeddings). |
| **Fast Search** | Vector databases can quickly find similar embeddings among millions of documents. |
| **Context Understanding** | Unlike keyword matching, embeddings understand that "automobile" and "car" mean the same thing. |

**The Process:**

1. **Input:** Your text chunk (from the chunking step)
2. **Processing:** An embedding model (a trained neural network) analyzes the text
3. **Output:** A vector (list of numbers) representing the text's meaning
4. **Storage:** This vector is saved in your vector database alongside a reference to the original text

### What Makes a Good Embedding?

Good embeddings have these properties:

| Property | Meaning |
|----------|---------|
| **Semantic Similarity** | Similar meanings → similar vectors (nearby in mathematical space) |
| **Dimensionality** | More dimensions (numbers) can capture more nuance, but cost more to store and search |
| **Consistency** | The same text always produces the same embedding |
| **Cross-lingual** | Some models produce similar embeddings for the same meaning across languages |

### How Similarity is Measured

When you search for information, the system compares your query's embedding against all stored embeddings using mathematical formulas:

| Method | How It Works | When to Use |
|--------|--------------|-------------|
| **Cosine Similarity** | Measures the angle between two vectors (ignores magnitude) | Most common; works well for text |
| **Euclidean Distance** | Measures straight-line distance between vectors | When magnitude matters |
| **Dot Product** | Multiplies corresponding numbers and sums them | Fast computation; used by many databases |

### Popular Embedding Models

| Model | Provider | Dimensions | Best For |
|-------|----------|------------|----------|
| **all-MiniLM-L6-v2** ✅ | Sentence Transformers (Open Source) | 384 | Free; runs locally; our chosen model |
| **all-mpnet-base-v2** | Sentence Transformers (Open Source) | 768 | Free; higher quality upgrade path |
| **bge-small-en-v1.5** | BAAI (Open Source) | 384 | Free; high quality |
| **nomic-embed-text-v1.5** | Nomic AI (Open Source) | 768 | Free; very good quality |
| **BGE-large-en** | BAAI (Open Source) | 1,024 | Free; best open-source quality |
| **text-embedding-3-small** | OpenAI | 1,536 | Paid API; cost-effective general use |
| **text-embedding-3-large** | OpenAI | 3,072 | Paid API; higher quality, complex queries |
| **voyage-3** | Voyage AI | 1,024 | Paid API; optimised for retrieval |
| **embed-english-v3.0** | Cohere | 1,024 | Paid API; English-focused applications |
| **Titan Embeddings** | Amazon Bedrock | 1,536 | Paid API; AWS-integrated workflows |
| **Gecko** | Google Vertex AI | 768 | Paid API; Google Cloud integration |

---

### Our Choice: Local Embeddings with `all-MiniLM-L6-v2`

We use a **free, open-source embedding model** that runs locally on Railway's compute — no API calls, no API keys, no per-token costs. The model is loaded once when the worker starts and stays in memory.

#### Why Local Instead of Paid APIs?

| Factor | Local Model (Our Choice) | Paid API (OpenAI / Voyage AI) |
|--------|--------------------------|-------------------------------|
| **Cost** | $0 — runs on Railway compute | ~$0.02–$0.06 per 1M tokens |
| **Speed** | Very fast — no network latency | Slower — requires API round-trip |
| **Privacy** | Text never leaves your server | Text is sent to a third party |
| **Availability** | Always available — no API outages | Subject to provider downtime |
| **Rate Limits** | None — limited only by CPU | Per-minute/per-day token limits |
| **Setup** | `pip install sentence-transformers` | API key + billing account |

#### Our Chosen Model: `all-MiniLM-L6-v2`

| Property | Value |
|----------|-------|
| **Provider** | Sentence Transformers (Open Source) |
| **Dimensions** | 384 |
| **Download Size** | 80 MB |
| **RAM Usage** | ~250 MB |
| **Max Input** | 256 word pieces (~200 words) |
| **Speed** | Very fast on CPU (no GPU needed) |
| **Quality** | Good — sufficient for knowledge bases under 100K chunks |
| **License** | Apache 2.0 (fully open) |

**How it works:**
1. Install the `sentence-transformers` Python package
2. Load the model once at worker startup: `model = SentenceTransformer('all-MiniLM-L6-v2')`
3. Embed text: `vector = model.encode("your text here")` → returns a 384-dimension vector
4. Store the vector in PostgreSQL via pgvector
5. Query by embedding your search text with the same model and using cosine similarity

#### Upgrade Path

If retrieval quality needs improvement later, switch to a larger local model:

| Model | Dimensions | Size | Quality | Speed | When to Switch |
|-------|-----------|------|---------|-------|----------------|
| **`all-MiniLM-L6-v2`** ✅ | 384 | 80 MB | Good | Very fast | Current choice |
| `all-mpnet-base-v2` | 768 | 420 MB | Better | Fast | If retrieval precision drops |
| `bge-small-en-v1.5` | 384 | 130 MB | Good | Fast | Alternative at same dimensions |
| `nomic-embed-text-v1.5` | 768 | 550 MB | Very good | Moderate | For larger knowledge bases |

Switching models requires re-embedding all existing documents and updating the pgvector column dimensions. This is a one-time migration.

---

### Paid API Alternatives (For Reference)

If you later decide to use a paid embedding service (e.g., for higher quality or multilingual support), these are the main options:

| Provider | Model | Dimensions | Pricing | Best For |
|----------|-------|-----------|---------|----------|
| **OpenAI** | text-embedding-3-small | 1,536 | ~$0.02/1M tokens | General content, largest community |
| **OpenAI** | text-embedding-3-large | 3,072 | ~$0.13/1M tokens | Maximum quality |
| **Voyage AI** | voyage-3 | 1,024 | ~$0.06/1M tokens | Optimised for retrieval tasks |
| **Voyage AI** | voyage-code-3 | 1,024 | ~$0.06/1M tokens | Code and technical documentation |
| **Cohere** | embed-english-v3.0 | 1,024 | Per API call | English-focused, multilingual options |

---

### Python Packages for Embeddings

| Package | Description | Best For | Cost |
|---------|-------------|----------|------|
| **Sentence Transformers** ✅ | Open-source library for local embedding models — **our chosen tool** | Free, offline, privacy-focused | Free |
| **FastEmbed** | Lightweight, fast local embeddings (alternative to Sentence Transformers) | Speed-critical applications | Free |
| **Hugging Face Transformers** | Access to thousands of open-source models | Research, custom models | Free |
| **LangChain** | Unified interface for multiple embedding providers | Switching between providers easily | Free |
| **LlamaIndex** | Integrates embedding generation into RAG pipelines | End-to-end RAG applications | Free |
| **ChromaDB** | Vector database with built-in embedding functions | Simple all-in-one setup | Free |
| **OpenAI Python SDK** | Official client for OpenAI embedding models | Paid API alternative | Pay per token |
| **Voyage AI SDK** | Specialized embeddings for code and retrieval | Paid API alternative | Pay per token |
| **Cohere SDK** | Official client for Cohere embedding models | Paid API alternative | Pay per API call |

### Embedding Considerations for AI Knowledge Bases

| Factor | Guidance |
|--------|----------|
| **Model Choice** | We use `all-MiniLM-L6-v2` (384 dims, local, free). Upgrade to `all-mpnet-base-v2` (768 dims) if retrieval quality needs improvement |
| **Dimension Trade-off** | Higher dimensions = better quality but more storage and slower search. 384 is sufficient for <100K chunks |
| **Batch Processing** | Embed multiple chunks in a single `model.encode()` call for efficiency |
| **Caching** | Store embeddings permanently in pgvector; re-embedding is wasteful even when free (costs compute time) |
| **Consistency** | Always use the same model for queries as you used for documents. Mixing models = broken search |
| **Model Loading** | Load the model once at worker startup and keep it in memory (~250 MB for MiniLM) |

### Common Pitfalls to Avoid

| Pitfall | Problem | Solution |
|---------|---------|----------|
| **Mixing Models** | Query and document embeddings from different models won't match | Use `all-MiniLM-L6-v2` consistently for both indexing and querying |
| **Ignoring Token Limits** | Text exceeding model limits gets truncated silently | Chunk text to 500–1,000 tokens before embedding (MiniLM max: ~256 word pieces) |
| **No Preprocessing** | Garbage in = garbage out | Clean text (remove noise, normalize formatting) |
| **Embedding Entire Documents** | Single embedding loses detail | Chunk first, then embed each chunk |
| **Switching Models Without Re-embedding** | Old embeddings are incompatible with new model dimensions | Re-embed all documents when changing models |

---

## Step 4: Store Embeddings in Vector Database

The embeddings are saved in a **vector database** hosted on Railway. 

A **vector database** is a special type of database designed to store and search embeddings (vectors). Unlike traditional databases that find exact matches, vector databases find *similar* items—which is exactly what RAG needs.

**What gets stored:**  
- The embedding (vector)
- A reference to the original document
- Optional metadata (title, date, tags)

---

### Vector Databases Available on Railway

Railway makes it easy to deploy databases with one click. Here are the main vector database options available:

#### 1. PostgreSQL + pgvector

**What it is:** PostgreSQL is the world's most popular open-source database. **pgvector** is an extension that adds vector search capabilities to PostgreSQL.

| Aspect | Details |
|--------|---------|
| **Type** | Traditional database + vector extension |
| **Deployment** | One-click on Railway (PostgreSQL template) |
| **How it works** | Store vectors in a regular PostgreSQL table with a special vector column |

**Pros:**
| Advantage | Why It Matters |
|-----------|----------------|
| ✅ **Familiar technology** | If you know SQL, you already know how to use it |
| ✅ **All-in-one database** | Store vectors, metadata, and regular data in one place |
| ✅ **No extra services** | One database handles everything; simpler architecture |
| ✅ **Mature and reliable** | PostgreSQL has decades of production use |
| ✅ **Full-text search built-in** | Native keyword search for hybrid search without extra tools |
| ✅ **Lower cost** | No separate vector database service to pay for |
| ✅ **Railway-native** | First-class support on Railway with easy setup |

**Cons:**
| Disadvantage | Why It Matters |
|--------------|----------------|
| ❌ **Slower at scale** | Performance drops with millions of vectors compared to purpose-built databases |
| ❌ **Manual setup** | Need to install pgvector extension and create indexes yourself |
| ❌ **Limited advanced features** | Fewer vector-specific optimizations than dedicated databases |
| ❌ **Index tuning required** | Need to understand HNSW vs IVFFlat indexes for best performance |

**Best for:** Small to medium knowledge bases (under 1 million vectors), teams who want simplicity, projects already using PostgreSQL.

---

#### 2. Qdrant

**What it is:** Qdrant is a purpose-built vector database designed from the ground up for AI applications. It's fast, feature-rich, and optimized for similarity search.

| Aspect | Details |
|--------|---------|
| **Type** | Dedicated vector database |
| **Deployment** | One-click on Railway (Qdrant template) |
| **How it works** | Stores vectors in optimized data structures designed for fast similarity search |

**Pros:**
| Advantage | Why It Matters |
|-----------|----------------|
| ✅ **Built for vectors** | Every feature is optimized for embedding search |
| ✅ **Very fast** | Handles millions of vectors with low latency |
| ✅ **Rich filtering** | Filter by metadata while searching (e.g., "find similar docs from 2024") |
| ✅ **Hybrid search built-in** | Native support for combining semantic + keyword search |
| ✅ **Easy API** | Simple REST and gRPC APIs; great Python client |
| ✅ **Payload storage** | Store metadata alongside vectors efficiently |
| ✅ **Quantization** | Compress vectors to save memory and speed up search |

**Cons:**
| Disadvantage | Why It Matters |
|--------------|----------------|
| ❌ **Another service to manage** | Adds complexity; one more thing that can fail |
| ❌ **Learning curve** | New concepts if you're used to traditional databases |
| ❌ **Less mature** | Newer than PostgreSQL; smaller community |
| ❌ **Separate from main data** | May need to sync with your primary database |

**Best for:** Large knowledge bases, projects needing advanced filtering, applications where search speed is critical.

---

#### 3. Weaviate

**What it is:** Weaviate is an open-source vector database with built-in AI capabilities, including automatic embedding generation and hybrid search.

| Aspect | Details |
|--------|---------|
| **Type** | AI-native vector database |
| **Deployment** | Available on Railway via Docker template |
| **How it works** | Stores vectors with a schema; can generate embeddings automatically |

**Pros:**
| Advantage | Why It Matters |
|-----------|----------------|
| ✅ **Built-in embeddings** | Can generate embeddings for you (no separate API calls) |
| ✅ **Hybrid search native** | Combines keyword + semantic search out of the box |
| ✅ **GraphQL API** | Modern, flexible query interface |
| ✅ **Schema-based** | Structured data model helps organize large knowledge bases |
| ✅ **Multi-tenancy** | Built-in support for multiple users/projects in one instance |
| ✅ **Generative search** | Can integrate with LLMs directly for RAG |

**Cons:**
| Disadvantage | Why It Matters |
|--------------|----------------|
| ❌ **More complex** | More features = steeper learning curve |
| ❌ **Heavier resource use** | Requires more RAM and CPU than simpler options |
| ❌ **Schema required** | Must define data structure upfront |
| ❌ **Docker deployment** | Slightly more setup than one-click templates |

**Best for:** Projects wanting an all-in-one AI platform, teams who want built-in embedding generation, multi-tenant applications.

---

#### 4. Redis (with Vector Search)

**What it is:** Redis is a lightning-fast in-memory database. Recent versions include vector search capabilities through the Redis Stack.

| Aspect | Details |
|--------|---------|
| **Type** | In-memory database + vector module |
| **Deployment** | One-click on Railway (Redis template, use Redis Stack) |
| **How it works** | Stores vectors in memory for extremely fast access |

**Pros:**
| Advantage | Why It Matters |
|-----------|----------------|
| ✅ **Extremely fast** | In-memory storage means microsecond response times |
| ✅ **Simple setup** | Easy to deploy on Railway |
| ✅ **Multi-purpose** | Also handles caching, sessions, queues—many uses |
| ✅ **Real-time updates** | Changes are instantly searchable |
| ✅ **Familiar to developers** | Widely used; lots of documentation |

**Cons:**
| Disadvantage | Why It Matters |
|--------------|----------------|
| ❌ **Memory-limited** | All data must fit in RAM; expensive at scale |
| ❌ **Persistence concerns** | In-memory data can be lost; need careful backup config |
| ❌ **Less mature vector features** | Vector search is newer; fewer features than dedicated DBs |
| ❌ **Cost at scale** | RAM is expensive; large knowledge bases get costly |

**Best for:** Small knowledge bases, real-time applications, projects already using Redis for caching.

---

### Head-to-Head Comparison

| Factor | PostgreSQL + pgvector | Qdrant | Weaviate | Redis |
|--------|----------------------|--------|----------|-------|
| **Setup Difficulty** | Easy | Easy | Medium | Easy |
| **Learning Curve** | Low (if you know SQL) | Medium | Higher | Low |
| **Speed (small data)** | Fast | Very Fast | Fast | Extremely Fast |
| **Speed (large data)** | Slower | Very Fast | Fast | Limited by RAM |
| **Hybrid Search** | Manual setup | Built-in | Built-in | Limited |
| **Filtering** | SQL (powerful) | Rich | Rich | Moderate |
| **Cost** | Low | Low | Medium | High (RAM cost) |
| **Railway Support** | Native | Template | Docker | Native |
| **Community Size** | Huge | Growing | Growing | Huge |
| **Max Scale** | ~1M vectors | 100M+ vectors | 100M+ vectors | RAM-limited |

---

### Recommendation for Your RAG Workflow

#### Start With: **PostgreSQL + pgvector**

For most beginners building their first RAG knowledge base on Railway, we recommend **PostgreSQL with pgvector**:

| Reason | Explanation |
|--------|-------------|
| **Simplest architecture** | One database for everything—vectors, documents, metadata, users |
| **Familiar technology** | SQL skills transfer directly; tons of tutorials available |
| **Railway-native** | First-class support, one-click deploy, easy backups |
| **Cost-effective** | No separate vector database bill |
| **Good enough for most projects** | Handles hundreds of thousands of vectors easily |
| **Easy hybrid search** | PostgreSQL's built-in full-text search works alongside pgvector |

**When to start here:**
- You're new to RAG and want the simplest path
- Your knowledge base has fewer than 500,000 documents
- You want one database for everything
- Budget is a concern

---

#### Upgrade To: **Qdrant**

When your RAG system grows or needs more power, consider upgrading to **Qdrant**:

| Reason | Explanation |
|--------|-------------|
| **Scales effortlessly** | Handles millions of vectors without slowing down |
| **Built-in hybrid search** | No manual setup; just works |
| **Better filtering** | Complex metadata queries remain fast |
| **Production-ready** | Designed for high-traffic AI applications |

**When to switch:**
- Your knowledge base exceeds 500,000 documents
- Search is getting slow
- You need advanced filtering by metadata
- You want native hybrid search without manual SQL

---

#### Consider: **Weaviate**

Choose Weaviate if you want an all-in-one AI platform:

| Reason | Explanation |
|--------|-------------|
| **Built-in embeddings** | Don't want to manage embedding API calls separately |
| **Multi-tenant needs** | Building a platform for multiple users/organizations |
| **AI-native features** | Want tight LLM integration built into the database |

---

#### Consider: **Redis**

Choose Redis for specific use cases:

| Reason | Explanation |
|--------|-------------|
| **Real-time requirements** | Need microsecond response times |
| **Small, fast datasets** | Knowledge base fits comfortably in memory |
| **Already using Redis** | Want to consolidate infrastructure |

---

### Recommended Progression Path

```
┌─────────────────────────────────────────────────────────────┐
│                   YOUR RAG JOURNEY                          │
└─────────────────────────────────────────────────────────────┘

STAGE 1: Getting Started
├── Database: PostgreSQL + pgvector
├── Scale: Up to 100K documents
├── Why: Simplest setup, lowest cost, learn the basics
└── Railway: One-click PostgreSQL template

STAGE 2: Growing
├── Database: Still PostgreSQL + pgvector (with tuned indexes)
├── Scale: 100K - 500K documents
├── Why: Optimize before migrating; pgvector is capable
└── Action: Add HNSW indexes, tune parameters

STAGE 3: Scaling Up
├── Database: Migrate to Qdrant
├── Scale: 500K+ documents
├── Why: Purpose-built performance, better hybrid search
└── Railway: One-click Qdrant template

STAGE 4: Enterprise
├── Database: Qdrant or Weaviate
├── Scale: Millions of documents
├── Why: Advanced features, multi-tenancy, high availability
└── Consider: Managed cloud options for critical workloads
```

---

## Step 5: Retrieve and Generate (Hybrid Search)

**What happens:**  
When a user asks a question:
1. The question is converted to an embedding
2. The vector database finds documents with similar embeddings
3. Those documents are sent to the AI along with the question
4. The AI generates an answer using the retrieved context

**Why it matters:**  
The AI now answers based on *your* specific knowledge, not just its general training data.

---

## Hybrid Search Retrieval: Deep Dive

### What is Hybrid Search?

**Hybrid search** combines two different search methods to find the most relevant documents:

| Method | How it Works | Best For |
|--------|--------------|----------|
| **Semantic Search** | Finds documents with similar *meaning* using embeddings | Understanding context, synonyms, concepts |
| **Keyword Search** | Finds documents containing exact words (BM25/full-text) | Specific terms, names, codes, acronyms |

**Why combine them?**  
Neither method is perfect alone:
- Semantic search might miss exact terms (e.g., "Error Code 5012")
- Keyword search might miss related concepts (e.g., "car" won't find "automobile")

Hybrid search gets the best of both worlds.

---

### How Hybrid Search Works

```
         User Query: "How do I fix Error 5012?"
                          │
          ┌───────────────┴───────────────┐
          │                               │
          ▼                               ▼
   ┌─────────────┐                 ┌─────────────┐
   │  Semantic   │                 │   Keyword   │
   │   Search    │                 │   Search    │
   │ (Embeddings)│                 │   (BM25)    │
   └──────┬──────┘                 └──────┬──────┘
          │                               │
          │  Results: docs about          │  Results: docs with
          │  "fixing errors"              │  "Error 5012"
          │                               │
          └───────────────┬───────────────┘
                          │
                          ▼
                 ┌─────────────────┐
                 │  Combine Scores │
                 │  (Reciprocal    │
                 │   Rank Fusion)  │
                 └────────┬────────┘
                          │
                          ▼
                 ┌─────────────────┐
                 │  Top K Results  │
                 │  (Best of Both) │
                 └─────────────────┘
```

---

### How It Interacts with the Workflow

| Workflow Step | Hybrid Search Interaction |
|---------------|---------------------------|
| **Step 1: Documents** | Documents are indexed for *both* keyword search and embeddings |
| **Step 2: Embeddings** | Embeddings enable the semantic search component |
| **Step 3: Vector DB** | Database must support both vector search AND full-text search |
| **Step 4: Retrieval** | Both search methods run in parallel, results are merged |

**Key Integration Point:**  
Your vector database on Railway needs to support hybrid search. Options include:
- **PostgreSQL + pgvector** (with full-text search via `tsvector`)
- **Weaviate** (built-in hybrid search)
- **Qdrant** (sparse + dense vectors)

---

### Limitations of Hybrid Search

| Limitation | Description | Mitigation |
|------------|-------------|------------|
| **Tuning Complexity** | The `alpha` weight needs adjustment for your data | Start with 0.5, test with real queries, adjust based on results |
| **Increased Latency** | Two searches run instead of one | Run searches in parallel; use database-level hybrid search |
| **Storage Overhead** | Storing both embeddings and keyword indexes | Accept trade-off; storage is cheaper than poor results |
| **Keyword Language Dependency** | Full-text search is language-specific | Configure correct language in PostgreSQL; consider multilingual models |
| **No Perfect Ranking** | RRF is a heuristic, not optimal for all cases | Experiment with different fusion methods (weighted sum, learned ranking) |

---

### Key Considerations for Your Implementation

#### 1. **Alpha Weight Selection**
- `alpha = 0.5` → Equal weight to both methods
- `alpha > 0.7` → Favor semantic (better for conceptual queries)
- `alpha < 0.3` → Favor keyword (better for exact matches)

**Recommendation:** Start with `alpha = 0.6` and log which method finds the winning document. Adjust based on patterns.

#### 2. **Chunk Size for Documents**
- Large chunks = more context but less precision
- Small chunks = more precision but may lose context

**Recommendation:** Start with 500-1000 tokens per chunk with 100-token overlap.

#### 3. **Which Vector Database?**
| Option | Pros | Cons |
|--------|------|------|
| **PostgreSQL + pgvector** | Familiar, Railway-native, full SQL support | Manual hybrid search setup |
| **Weaviate** | Built-in hybrid search, easy setup | Separate service to manage |
| **Qdrant** | Fast, supports sparse vectors natively | Learning curve |

#### 4. **Embedding Model Choice**
- `all-MiniLM-L6-v2` ✅ → Free, local, 384 dimensions — our chosen model
- `all-mpnet-base-v2` → Free, local, 768 dimensions — upgrade if retrieval quality needs improvement
- Paid alternatives (OpenAI, Voyage AI) available if budget allows in the future

---

## Key Terms

| Term | Simple Definition |
|------|-------------------|
| **RAG** | A method to enhance AI responses with your own documents |
| **Preprocessing** | Preparing raw documents by extracting, cleaning, and formatting text |
| **Extraction** | Pulling text content out of files like PDFs, Word docs, or web pages |
| **OCR** | Optical Character Recognition; converting images of text into actual text |
| **Normalization** | Making text consistent (fixing encoding, spacing, formatting) |
| **Chunking** | Splitting large documents into smaller pieces for processing |
| **Chunk Overlap** | Shared text between consecutive chunks to preserve context at boundaries |
| **Embedding** | A list of numbers that represents the meaning of text |
| **Vector** | Another name for an embedding; a list of numbers in mathematical space |
| **Dimensions** | The count of numbers in an embedding (e.g., 384 dimensions = 384 numbers for `all-MiniLM-L6-v2`) |
| **Cosine Similarity** | A mathematical formula to measure how similar two embeddings are |
| **Token** | A unit of text (roughly 4 characters or ¾ of a word in English) |
| **Vector Database** | A database optimized for storing and searching embeddings quickly |
| **pgvector** | An extension that adds vector search to PostgreSQL |
| **Qdrant** | A purpose-built vector database optimized for AI applications |
| **Weaviate** | An AI-native vector database with built-in embedding generation |
| **Hybrid Search** | Combining semantic search and keyword search for better results |
| **Semantic Search** | Finding documents by meaning rather than exact keyword matches |
| **HNSW Index** | A fast index type for vector search (used in pgvector and Qdrant) |
| **Railway** | A cloud platform for hosting your database and services |

---

## Next Steps

1. ~~Set up a Railway project~~ ✅ Done
2. ~~Configure document storage~~ ✅ Done (Railway Object Storage)
3. ~~Deploy a vector database~~ ✅ Done (PostgreSQL + pgvector on Railway)
4. Install `sentence-transformers` and load `all-MiniLM-L6-v2` on Railway worker
5. Migrate pgvector `embeddings` table from `vector(1536)` → `vector(384)`
6. Build the embedding pipeline (chunk → embed → store)
7. Build the retrieval logic (embed query → pgvector cosine search → return chunks)
