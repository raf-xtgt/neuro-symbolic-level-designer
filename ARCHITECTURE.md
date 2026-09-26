# System Architecture: AI-Assisted 2D Isometric Level Generator for Flame Engine

## 1. Purpose and Scope

This document specifies the production architecture for an automated level design system. 
The system generates 2D isometric game levels for the Flame game engine. 
The system converts input assets and design prompts into game-ready map files and Dart source code.

### 1.1 Core Objectives
* Remove manual level layout work in Tiled Map Editor.
* Accept raw spritesheets as the primary asset input.
* Prevent low-quality output through rigorous data validation.
* Output valid Tiled map files, tileset files, and Dart integration code for the Flame engine.

---

## 2. System Architecture Overview

The system operates on a **neuro-symbolic design philosophy ("Agents Plan, Algorithms Fill")**:
* **Agents** handle high-level semantic reasoning, room topology, theme distribution, and intent interpretation.
* **Deterministic algorithms (OpenCV, WFC, A\*, BSP)** handle image slicing, coordinate math, micro-tile placement, and geometry validation.
* **LangGraph StateGraph** coordinates the lifecycle with a cyclic self-healing feedback loop.

```mermaid
flowchart TD
    subgraph Inputs ["1. Input Layer"]
        A1["Spritesheets (.png) [Mandatory]"]
        A2["Existing Tilesets (.tsx/.tsj) [Optional]"]
        A3["Existing Maps (.tmx/.tmj) [Optional]"]
        A4["User Design Prompt [Mandatory]"]
    end

    subgraph Ingestion ["2. Data Ingestion Pipeline"]
        B1["OpenCV Pre-Processor & Slicer"]
        B2["Parallel VLM Analysis (Pydantic / Instructor)"]
        B3["Asset Harmonizer (Code-First + LLM Resolver)"]
        B4[("Asset Catalog (asset_catalog.json)")]
    end

    subgraph Planning ["3. Level Design Planning Pipeline (Neuro-Symbolic)"]
        C1["Spatial Topology Agent (Room Graph DSL)"]
        C2["Isometric Stacking & Occlusion Agent"]
        C3["Gameplay & Spawner Agent"]
        C4["Algorithmic Dressing Engine (WFC / Autotiling)"]
        C5["Deterministic Constraint Validator (A* & Bounds)"]
        C6[("Level Specification Plan (level_plan.json)")]
        
        C5 -- "Validation Fails (Structured Error Feedback)" --> C1
        C5 -- "Validation Passes" --> C6
    end

    subgraph Execution ["4. Execution Pipeline"]
        D1["Deterministic Map Compiler"]
        D2["Deterministic Tileset Compiler"]
        D3["Template-Assisted Flame Code Generator"]
        D4["Verification Engine"]
    end

    subgraph Outputs ["5. Output Bundle"]
        E1["Map File (.tmj / .tmx)"]
        E2["Tileset File (.tsj / .tsx) + Images"]
        E3["Flame Integration Code (.dart)"]
        E4["Level Validation Report (summary.json)"]
    end

    Inputs --> Ingestion
    A1 & A2 & A3 --> B1
    B1 --> B2 --> B3 --> B4

    B4 & A4 --> Planning
    C1 --> C2 --> C3 --> C4 --> C5

    B4 & C6 --> Execution
    D1 --> E1
    D2 --> E2
    D3 --> E3
    D4 --> E4
```

---

## 3. Pipeline 1: Data Ingestion Pipeline

The Data Ingestion Pipeline converts raw graphic files into structured semantic data. 
This pipeline prevents invalid asset processing in downstream components. 
It uses deterministic tools and specialized software agents.

```mermaid
flowchart LR
    subgraph S1 ["Step 1: Ingestion"]
        P1["Spritesheet (.png)"] --> DET1["Grid & Contour Slicer"]
        OPT1["Legacy Files (.tsx / .tmx)"] --> DET2["Tiled XML/JSON Parser"]
    end

    subgraph S2 ["Step 2: Parallel Agent Analysis"]
        DET1 & DET2 --> AG1["Tile Boundary Agent"]
        DET1 & DET2 --> AG2["Tile Classification Agent"]
        DET1 & DET2 --> AG3["Collision & Physics Agent"]
        DET1 & DET2 --> AG4["Entity & Prop Agent"]
    end

    subgraph S3 ["Step 3: Harmonization"]
        AG1 & AG2 & AG3 & AG4 --> HARMON["Asset Harmonizer Agent"]
        HARMON --> CAT[("Asset Catalog (asset_catalog.json)")]
    end
```

### 3.1 Deterministic Pre-Processor (OpenCV / PIL)
The deterministic pre-processor analyzes incoming files before agents start work, avoiding costly and imprecise vision token usage for mechanical slicing.

* **Dual-Strategy Slicing Pipeline (Contour and Grid):**
  * **Primary (Contour Slicing):** Uses `cv2.findContours` and alpha thresholding to detect sprite boundaries with transparent padding.
  * **Fallback (Fixed-Grid Slicing):** Continuous spritesheets lack transparent gutters between tiles. If contour analysis fails or detects touching tiles, the system switches to uniform grid slicing (for example: 64x32 or 32x16 pixels).
  * Calculates default isometric cell dimensions from standard 2:1 projection geometry.
  * Automatically isolates individual tile chips and generates contact sheets for agent consumption.
* **Legacy Format Parser:**
  * Reads optional `.tsx`, `.tsj`, `.tmx`, and `.tmj` files if provided.
  * Extracts existing tile identifiers, tile counts, and custom properties.
  * Bypasses visual guessing for pre-defined tiles.

### 3.2 Granular Analysis Agents (Parallel Execution via Constrained Decoding)
Four specialized agents analyze the sliced graphics in parallel. To eliminate prompt fragility and schema errors, all agents run under **grammar-constrained decoding (e.g., Instructor or Outlines with Pydantic)**.

#### 3.2.1 Tile Boundary Agent
* **Role:** Calculates sprite bounds and anchor points.
* **Input:** Sliced image tiles and dimension data.
* **Function:** 
  * Fits the standard isometric base diamond (width $W$, height $H = W / 2$).
  * Calculates vertical offsets for tall structures (walls, pillars, trees) where height exceeds base tile height.
  * Assigns isometric origin coordinates `(x, y)` to prevent rendering displacement and sorting seams.

#### 3.2.2 Tile Classification Agent
* **Role:** Categorizes the functional role of each tile using multimodal VLM with strict enum schemas.
* **Input:** Visual sprite images + contact sheets.
* **Function:** 
  * Classifies tiles into exact types: `floor`, `wall`, `ramp`, `hazard`, `water`, or `decoration`.
  * Identifies surface material (for example: stone, dirt, wood, grass).
  * Sets the `walkable` boolean flag and tags visual style attributes.

#### 3.2.3 Collision and Physics Agent
* **Role:** Detects collision geometry through hybrid computer vision and semantic tagging.
* **Input:** Classified tiles and alpha channel outlines.
* **Function:**
  * Uses OpenCV contour extraction to generate precise 2D collision polygons for solid tiles.
  * Defines elevation values (`z-index`) and obstacle heights.
  * Flags tiles that block projectile paths or line of sight.

#### 3.2.4 Entity and Prop Extractor Agent
* **Role:** Separates dynamic entities from static terrain.
* **Input:** Unclassified sprites and non-grid graphics.
* **Function:**
  * Detects interactive objects (chests, doors, levers).
  * Identifies character and enemy sprites.
  * Marks item spawn points and interaction trigger areas.

### 3.3 Asset Harmonizer (Code-First with LLM Fallback)
* **Role:** Consolidates analysis results into a single canonical catalog.
* **Input:** Outputs from the four parallel analysis agents.
* **Function:**
  * **Deterministic Merger (Code-First):** Merges attributes, normalizes metadata, and assigns contiguous Global Tile IDs (GIDs).
  * **LLM Conflict Arbitration:** Invoked *only* when contradictory classifications occur (for example: if a tile is categorized as `wall` but also flagged `walkable: true`).
  * Generates the canonical `asset_catalog.json` file.

---

## 4. Pipeline 2: Level Design Planning Pipeline (Neuro-Symbolic)

The Level Design Planning Pipeline synthesizes the spatial layout of the level from `asset_catalog.json` and the user design prompt. 

To eliminate spatial drift and tile hallucinations inherent in LLMs generating raw 2D numerical arrays, this pipeline enforces a **hierarchical neuro-symbolic approach**:
1. **Agents plan macro-structures** via semantic graphs and aesthetic rules.
2. **Algorithms solve micro-placements** via procedural layout and Wave Function Collapse (WFC).
3. **LangGraph orchestrates the cyclic validation loop** with structured error feedback.

```mermaid
flowchart TD
    AC[("asset_catalog.json")] & PROMPT["User Prompt"] --> P1["1. Spatial Topology Agent\n(Outputs Room Graph DSL)"]
    P1 --> P2["2. Isometric Stacking & Occlusion Agent\n(Assigns Z-layers & Ramps)"]
    P2 --> P3["3. Gameplay & Spawner Agent\n(Places Entities on Walkable Graph)"]
    P3 --> P4["4. Algorithmic Dressing Engine\n(WFC / Autotiler Fills GIDs)"]
    P4 --> P5["5. Deterministic Constraint Validator\n(A* Pathfinding & Overlaps)"]
    
    P5 -- "Validation Fails (Structured Error Feedback)" --> P1
    P5 -- "Validation Passes" --> OUT[("level_plan.json")]
```

### 4.1 Granular Planning Components

#### 4.1.1 Spatial Topology Planner Agent (Room Graph DSL)
* **Design Philosophy:** The agent **does not output raw 2D tile arrays**. Instead, it generates a high-level **Semantic Room Graph DSL**.
* **Role:** Designs the macro narrative and architectural flow of the level.
* **Output:** A structured graph comprising:
  * **Room Nodes:** Purpose (`entrance`, `combat`, `puzzle`, `boss`, `treasure`), target dimensions, and relative compass bearings.
  * **Corridor Edges:** Connections between rooms (`straight`, `winding`, `chokepoint`).
* **Deterministic Layout Builder:** A procedural engine (BSP / graph placer) converts this room graph into an initial isometric grid footprint.

#### 4.1.2 Isometric Stacking & Occlusion Agent
* **Role:** Manages vertical elevation ($Z$) and prevents isometric depth-sorting issues.
* **Function:**
  * Assigns elevation layers (Layer 0: Ground, Layer 1: Elevated Platforms).
  * Inserts ramp tiles to logically link differing height tiers.
  * **Occlusion Guard:** Enforces true isometric 3D depth order.
    * Calculates sorting index using depth equation: $Depth = X + Y + Z$.
    * Calculates projected screen position: $Y_{screen} = (X + Y) \times \frac{H_{tile}}{2} - Z \times H_{elevation}$.
    * If geometry occludes lower walkable pathways ($Depth_{wall} > Depth_{path}$ and screen positions overlap), the agent flags visual occlusion risks. The agent then introduces camera clearance corridors or transparent cutouts.

#### 4.1.3 Gameplay and Spawner Agent
* **Role:** Places gameplay entities relative to topological landmarks.
* **Function:**
  * Positions `PlayerSpawn` in the designated entrance node.
  * Positions `ExitTrigger` or objectives at the maximum topological distance from spawn.
  * Distributes enemies and hazards along corridor bottlenecks and combat arena zones.
  * Guarantees entities are placed strictly on coordinates marked `walkable: true`.

#### 4.1.4 Algorithmic Dressing Engine (Wave Function Collapse / Autotiling)
* **Design Philosophy:** Offload micro-tile selection from LLMs to constraint solvers.
* **Agent Role (Aesthetic Stylist):** Selects the **thematic distribution weights** (for example: `80% clean_stone, 15% cracked_stone, 5% mossy_stone; corners: stone_wall_trim`) based on the user prompt.
* **Deterministic WFC / Autotiling Solver:** Consumes the agent's style weights and the `asset_catalog.json` socket constraints to:
  * Select exact GIDs for floor variations.
  * Automatically resolve isometric wall corners, outer boundaries, and border transitions.
  * Scatter non-blocking decorative props without obstructing critical pathfinding.
* **WFC Contradiction and Fallback Strategy:**
  * WFC can reach an unsolvable contradiction when no valid tile matches adjacent socket constraints.
  * **Step 1 (Backtracking):** The solver rewinds up to $M$ collapse steps to choose alternative tile candidates.
  * **Step 2 (Seed Restart):** If backtracking fails, the solver restarts with an incremented random seed (up to 3 retries).
  * **Step 3 (Safe Default Fallback):** If retries fail, the solver forces a neutral default floor tile (`walkable: true`, base elevation) at the contradiction point to guarantee completion.

### 4.2 Deterministic Constraint Validator & LangGraph Self-Healing Loop
The validator audits the compiled level using deterministic game-logic checks. The pipeline is implemented as a **LangGraph StateGraph**: if any check fails, a structured error payload is routed back to the planning agents for automatic re-planning (up to $N$ retry iterations).

* **Isometric A\* Pathfinding Check:** Simulates navigation to guarantee an uninterrupted, walkable path from `PlayerSpawn` to `ExitTrigger`.
* **Collision Overlap Check:** Verifies that no entity or prop spawns inside solid wall collision polygons.
* **Asset Availability Check:** Confirms that every placed Tile ID strictly exists in `asset_catalog.json`.
* **Boundary Integrity Check:** Verifies that perimeter walls or impassable chasms surround all playable boundaries to prevent player out-of-bounds exploits.

---

## 5. Pipeline 3: Execution Pipeline

The Execution Pipeline converts the validated `level_plan.json` into production files.

```mermaid
flowchart LR
    LP[("level_plan.json")] & AC[("asset_catalog.json")] --> MC["Deterministic Map Compiler"]
    LP & AC --> TC["Deterministic Tileset Compiler"]
    LP & AC --> GC["Template-Assisted Flame Code Generator"]
    
    MC --> TMJ["level.tmj (.tmx)"]
    TC --> TSJ["tileset.tsj (.tsx) + .png"]
    GC --> DART["level_loader.dart"]
    
    TMJ & TSJ & DART --> VE["Verification Engine"]
    VE --> REP["summary.json"]
```

### 5.1 Deterministic Map Compiler
* Converts the layout plan into standard Tiled JSON (`.tmj`) or XML (`.tmx`).
* Sets map orientation to `isometric`.
* Encodes tile layers using standard uncompressed or base64 arrays.
* Writes object layers containing spawn coordinates, collision rectangles, and trigger zones.

### 5.2 Deterministic Tileset Compiler
* Generates the Tiled Tileset file (`.tsj` or `.tsx`).
* Embeds tile width, tile height, margins, and spacing.
* Embeds isometric tile offset values for tall wall sprites.
* Embeds collision polygon shapes directly into the tile definitions.

### 5.3 Template-Assisted Flame Code Generator Agent
* Uses **Jinja2 templating** for boilerplate architecture (`PositionComponent`, `HasGameReference`, `TiledComponent.load`, and generic hitbox loops).
* The LLM agent is focused strictly on synthesizing custom game mechanics and typed component callbacks:
  * Generates typed entity factories to spawn components from map object layers:
    * Spawns player entity with initial position and controller bindings.
    * Spawns enemy components with movement boundaries and patrol radii.
    * Adds `RectangleHitbox` and `PolygonHitbox` components to solid terrain using coordinates from the tileset.
    * Connects interactive trigger zones to Flame collision callback handlers.

### 5.4 Verification Engine
* Compiles the generated Dart code with the Flutter analysis tool.
* Checks that all image paths in the tileset match the Flutter asset directory structure.
* Generates a final `summary.json` file detailing:
  * Total tile counts.
  * Entity counts.
  * Playability validation status.

---

## 6. Data Contracts and Schemas

### 6.1 Asset Catalog Schema (`asset_catalog.json`)
The Data Ingestion Pipeline outputs this contract.

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "AssetCatalog",
  "type": "object",
  "required": ["tile_size", "tiles", "entities"],
  "properties": {
    "tile_size": {
      "type": "object",
      "required": ["width", "height"],
      "properties": {
        "width": { "type": "integer", "example": 64 },
        "height": { "type": "integer", "example": 32 }
      }
    },
    "tiles": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["id", "name", "category", "walkable", "offset"],
        "properties": {
          "id": { "type": "integer" },
          "name": { "type": "string" },
          "category": { "enum": ["floor", "wall", "ramp", "obstacle", "decoration"] },
          "walkable": { "type": "boolean" },
          "elevation": { "type": "integer", "default": 0 },
          "offset": {
            "type": "object",
            "required": ["x", "y"],
            "properties": {
              "x": { "type": "integer" },
              "y": { "type": "integer" }
            }
          },
          "collision_polygon": {
            "type": "array",
            "items": {
              "type": "object",
              "properties": {
                "x": { "type": "number" },
                "y": { "type": "number" }
              }
            }
          }
        }
      }
    },
    "entities": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["type", "name", "category"],
        "properties": {
          "type": { "type": "string" },
          "name": { "type": "string" },
          "category": { "enum": ["player", "enemy", "item", "trigger"] },
          "width": { "type": "number" },
          "height": { "type": "number" }
        }
      }
    }
  }
}
```

### 6.2 Room Topology Graph Contract (`topology_graph.json`)
The Spatial Topology Planner Agent outputs this intermediate macro-layout contract before procedural expansion and WFC dressing.

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "RoomTopologyGraph",
  "type": "object",
  "required": ["theme", "style_distribution", "rooms", "corridors"],
  "properties": {
    "theme": { "type": "string", "example": "dungeon_crypt" },
    "style_distribution": {
      "type": "object",
      "description": "Thematic weights consumed by the WFC / Autotiling engine",
      "additionalProperties": { "type": "number" }
    },
    "rooms": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["id", "purpose", "relative_position", "size"],
        "properties": {
          "id": { "type": "string" },
          "purpose": { "enum": ["entrance", "combat", "puzzle", "boss", "treasure"] },
          "relative_position": { "enum": ["north", "south", "east", "west", "center"] },
          "elevation": { "type": "integer", "default": 0 },
          "size": { "enum": ["small", "medium", "large"] }
        }
      }
    },
    "corridors": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["from_room", "to_room", "corridor_type"],
        "properties": {
          "from_room": { "type": "string" },
          "to_room": { "type": "string" },
          "corridor_type": { "enum": ["straight", "winding", "bridge"] }
        }
      }
    }
  }
}
```

### 6.3 Level Specification Plan Schema (`level_plan.json`)
The Level Design Planning Pipeline outputs this contract after WFC tile dressing and entity placement.

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "LevelSpecificationPlan",
  "type": "object",
  "required": ["map_properties", "layers", "objects"],
  "properties": {
    "map_properties": {
      "type": "object",
      "required": ["width", "height", "tile_width", "tile_height", "orientation"],
      "properties": {
        "width": { "type": "integer", "example": 25 },
        "height": { "type": "integer", "example": 25 },
        "tile_width": { "type": "integer", "example": 64 },
        "tile_height": { "type": "integer", "example": 32 },
        "orientation": { "type": "string", "enum": ["isometric"] }
      }
    },
    "layers": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["name", "elevation", "grid"],
        "properties": {
          "name": { "type": "string" },
          "elevation": { "type": "integer" },
          "grid": {
            "type": "array",
            "items": {
              "type": "array",
              "items": { "type": "integer" }
            }
          }
        }
      }
    },
    "objects": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["name", "type", "x", "y"],
        "properties": {
          "name": { "type": "string" },
          "type": { "type": "string" },
          "x": { "type": "number" },
          "y": { "type": "number" },
          "properties": { "type": "object" }
        }
      }
    }
  }
}
```

---

## 7. Flame Engine Integration Pattern

The generated Dart code uses the `Flame` component model and `flame_tiled`.

```dart
// Generated Flame Level Loader Component
import 'package:flame/components.dart';
import 'package:flame_tiled/flame_tiled.dart';

class GeneratedLevelLoader extends PositionComponent with HasGameReference {
  final String mapPath;
  late TiledComponent tiledMap;

  GeneratedLevelLoader({required this.mapPath});

  @override
  Future<void> onLoad() async {
    super.onLoad();

    // 1. Load the isometric map
    tiledMap = await TiledComponent.load(
      mapPath,
      Vector2(64, 32),
    );
    await add(tiledMap);

    // 2. Extract and spawn entities from the object group
    final objectGroup = tiledMap.tileMap.getLayer<ObjectGroup>('Entities');
    if (objectGroup != null) {
      for (final obj in objectGroup.objects) {
        _spawnObject(obj);
      }
    }

    // 3. Extract and configure collision boundaries
    final collisionGroup = tiledMap.tileMap.getLayer<ObjectGroup>('Collisions');
    if (collisionGroup != null) {
      for (final hitBox in collisionGroup.objects) {
        _createCollisionBox(hitBox);
      }
    }
  }

  void _spawnObject(TiledObject obj) {
    switch (obj.type) {
      case 'PlayerSpawn':
        // Spawn Player component at isometric coordinates
        break;
      case 'Enemy':
        // Spawn Enemy component
        break;
      case 'Trigger':
        // Spawn Area Trigger component
        break;
    }
  }

  void _createCollisionBox(TiledObject box) {
    // Attach hitbox component to level coordinate
  }
}
```

---

## 8. Summary of Technical Advantages

1. **Neuro-Symbolic Efficiency ("Agents Plan, Algorithms Fill"):** Eliminates prompt bloat and hallucinated numerical arrays by letting agents reason over semantic room graphs, while deterministic solvers (WFC, A\*, BSP) handle micro-tile indexing.
2. **Grammar-Constrained Decoding:** All VLM and LLM agent interactions run under strict Pydantic schemas (via Instructor / Outlines), mathematically guaranteeing schema conformity and eliminating parsing retries.
3. **Automated Self-Healing Loop:** LangGraph StateGraph connects deterministic validation gates with planning agents, feeding structured error payloads back for automated re-planning on edge cases.
4. **Low Friction for Developers:** Developers provide raw spritesheets and creative prompts—no manual JSON configuration, slicing, or Tiled drawing required.
5. **Deterministic Stability & Direct Flame Compatibility:** Critical pathfinding, coordinate math, WFC contradiction recovery, and serialization are 100% deterministic, compiling directly into Flutter/Flame asset pipelines.
