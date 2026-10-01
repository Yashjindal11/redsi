"""Test generation: mutation strategies and model-driven generators.

Strategy names map to the generator concepts in the design:

=====================  ==========================================
strategy               purpose
=====================  ==========================================
``paraphrase``         ParaphraseGenerator (template or model)
``noise``              typos / casing
``context_noise``      ContextNoiseGenerator
``long_context``       long-input stress
``role``               RoleGenerator (role-play framing)
``assumption``         AssumptionGenerator (false premises)
``ambiguity``          AmbiguityGenerator
``missing_information`` MissingInformationGenerator
``boundary``           BoundaryGenerator
``contradiction``      ContradictionGenerator
=====================  ==========================================

``LLMGenerator`` writes new tests from a description;
:mod:`redsi.spec` adds the SpecificationGenerator.
"""

from redsi.generators.llm import GenerationRequest, LLMGenerator
from redsi.generators.mutations import (
    DEFAULT_STRATEGIES,
    Ambiguity,
    Assumption,
    Boundary,
    ContextNoise,
    Contradiction,
    LongContext,
    MissingInformation,
    Mutation,
    Noise,
    Paraphrase,
    Role,
    build_strategies,
    derive,
    mutations,
    register_mutation,
)

__all__ = [
    "DEFAULT_STRATEGIES",
    "Ambiguity",
    "Assumption",
    "Boundary",
    "ContextNoise",
    "Contradiction",
    "GenerationRequest",
    "LLMGenerator",
    "LongContext",
    "MissingInformation",
    "Mutation",
    "Noise",
    "Paraphrase",
    "Role",
    "build_strategies",
    "derive",
    "mutations",
    "register_mutation",
]
