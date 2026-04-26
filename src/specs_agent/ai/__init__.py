"""AI-powered test scenario generation.

Two-tier system: Faker handles simple fields (email, date, uuid, int);
an optional in-process LLM (Gemma 4 via llama-cpp-python) generates
contextually relevant values for complex/domain-specific fields.

The LLM is fully optional — `pip install specs-agent[ai]` pulls in
llama-cpp-python, and the user provides a GGUF model file. Without it,
everything falls back to Faker (the existing behavior).
"""
