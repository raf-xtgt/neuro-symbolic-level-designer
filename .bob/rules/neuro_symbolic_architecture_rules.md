# IBM Bob Rule: Neuro-Symbolic Level Design Architecture ("Agents Plan, Algorithms Fill")

## 1. Scope and Objective
This rule instructs IBM Bob to maintain the neuro-symbolic division of labor specified in `ARCHITECTURE.md`.
Bob must prevent AI agent hallucinations in prompt-heavy level design tasks by strictly separating high-level semantic reasoning from low-level geometric and numerical computation.

---

## 2. Core Operational Principles

### 2.1 What Agents Must Do ("Agents Plan")
* **Semantic Planning:** Generate topological room graphs (`topology_graph.json`) specifying room purposes, approximate dimensions, and corridor linkages.
* **Thematic Style Selection:** Choose thematic weights and style distributions (e.g., `80% clean_stone, 15% cracked_stone, 5% mossy_stone`).
* **Gameplay Intent:** Decide player spawn locations, objective goals, and encounter pacing relative to room topological landmarks.
* **Semantic Asset Tagging:** Categorize visual sprites into functional roles (`floor`, `wall`, `ramp`, `hazard`, `decoration`) with grammar-constrained Pydantic schemas.

### 2.2 What Agents Must NOT Do
* **Never Output Raw 2D Tile Arrays:** Agents must never attempt to output raw numerical tile index matrices (e.g., $50 \times 50$ 2D arrays). This prevents spatial drift and hallucinated GIDs.
* **Never Compute Raw Coordinate Math:** Slicing pixels, fitting isometric diamonds, and calculating exact bounding polygon offsets must be delegated to deterministic scripts (OpenCV / numpy / dart math).

### 2.3 What Deterministic Solvers Must Do ("Algorithms Fill")
* **Dual-Strategy Slicing:** OpenCV alpha contour detection with uniform grid fallback.
* **Micro-Tile Placement:** Wave Function Collapse (WFC) and procedural autotiling based on agent style weights.
* **Validation & Playability:** A* pathfinding verification between player spawn and exit triggers.
* **File Compilation:** Deterministic serialization of validated layouts into standard Tiled JSON (`.tmj`) and XML (`.tmx`).

---

## 3. Self-Healing Validation Protocol
* When validation checks fail (e.g., disconnected path, entity-wall collision, missing GID):
  1. Capture the failure in a structured error payload.
  2. Route the error payload back to the planning agent in Bob's StateGraph.
  3. Re-plan only the affected room/layer up to $N$ retry iterations.
