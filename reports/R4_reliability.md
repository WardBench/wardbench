# R4 Reliability

Settings: {'model': 'qwen3-14b', 'temperature': 0, 'seed': 1, 'disable_thinking': True, 'n_ctx': 16384, 'policy_visibility': 'record', 'parallel_slots': 1}
Noise floor (success flips across 3 identical runs): **1/20 = 5%**.
Run seconds: [1712.6, 2348.8, 2423.9].
LocalAI/llama.cpp still fills a reasoning channel on tool turns; GPU kernels and prompt packing are not bit-stable even at temperature 0. Tool-argument JSON and search pagination can diverge enough to change graded success.
Tool-sequence agreement: 13/20; response_status agreement: 20/20.
