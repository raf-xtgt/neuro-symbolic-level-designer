"""Pipeline 1 analysis agents (ARCHITECTURE.md 3.2), one module per agent."""
from pipeline.ingestion.agents.base import AgentSpec, run_agent_batch
from pipeline.ingestion.agents.boundary import BOUNDARY
from pipeline.ingestion.agents.classification import CLASSIFICATION
from pipeline.ingestion.agents.collision import COLLISION
from pipeline.ingestion.agents.entity import ENTITY

AGENTS = (BOUNDARY, CLASSIFICATION, COLLISION, ENTITY)

__all__ = ["AGENTS", "AgentSpec", "BOUNDARY", "CLASSIFICATION", "COLLISION", "ENTITY", "run_agent_batch"]
