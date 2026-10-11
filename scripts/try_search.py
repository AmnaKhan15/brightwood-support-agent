"""Try the help-article search yourself.

    python scripts/try_search.py "can I return a clearance item"
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from brightwood_support.rag import HashingEmbedder, InMemoryStore, load_corpus  # noqa: E402

question = " ".join(sys.argv[1:]) or "How many days do I have to return something?"
store = InMemoryStore(HashingEmbedder())
store.add(load_corpus(ROOT / "data" / "help"))
print(f"Question: {question}\n")
for rank, (chunk, score) in enumerate(store.search(question, k=3), start=1):
    print(f"{rank}. [{chunk.id}]  similarity {score:.2f}")
    print(f"   {chunk.text}\n")
