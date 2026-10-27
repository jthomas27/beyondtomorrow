# Email-to-publication pipeline

``cmd + shift + v to preview``

This diagram shows the `BLOG:` email workflow and the revised source policy in
the workspace. Deployment of that policy to the Railway worker is pending.

```mermaid
flowchart TD
    A["Email trigger: BLOG topic"] --> B["Email worker<br/>Queue request and verify sender"]
    B --> C["Orchestrator role<br/>Coordinate workflow stages"]
    C --> D["Researcher<br/>Find sources and summarise findings"]

    S["Source policy<br/>Choose topic-relevant pages<br/>from approved sources"] --> D
    D -->|Fetched source text| I["Indexer role<br/>Split text into chunks<br/>and create embeddings"]
    I --> K[("RAG knowledge corpus<br/>pgvector + keyword search")]
    K -->|Retrieve relevant passages| D
    D --> E["Evidence check<br/>Minimum: 1 approved source<br/>and 1 supported finding<br/>Disclose gaps"]
    E --> W["Writer<br/>Draft article with citations"]
    W --> X["Editor<br/>Check facts, clarity and limitations"]
    X --> P["Publisher<br/>Validate content, attach image<br/>and publish"]
    P --> G["Publication<br/>Live article on Ghost"]

    K -. Additional context .-> W
    K -. Fact checking .-> X
    G -. Store article for future research .-> I
```

**RAG** retrieves relevant material from the stored knowledge corpus to support
research, writing and fact checking.

For email-triggered posts, Python performs the **Orchestrator** and **Indexer**
roles directly. Researcher, Writer, Editor and Publisher are AI agents. After
Ghost publication, the worker handles LinkedIn sharing and newsletter delivery,
then indexes the final article for future retrieval.

The evidence policy permits a scoped article with one approved source and one
supported finding. It prefers two independent publishers, carries unanswered
questions forward as disclosed gaps, and omits unsupported findings. An article
still needs a visible citation to its approved research evidence.
