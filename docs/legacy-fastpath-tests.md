# Legacy fast-path tests (skip by default)

These modules assert deterministic playbook / booking templates from the pre–LLM-first stack.
They are marked `legacy` and excluded from default `pytest` runs until Phase E removes the code.

| Module |
|--------|
| `tests/test_live_call_transcript.py` |
| `tests/test_vforms_booking_dialogue.py` |
| `tests/test_reception_grounded.py` |
| `tests/test_post_booking_smalltalk.py` |
| `tests/test_pool_faq_conversation.py` |
| `tests/test_resort_booking_regression.py` |
| `tests/test_booking_loop_regression.py` |
| `tests/test_conversation_sim.py` |
| `tests/test_live_voice_benchmark.py` |
| `tests/test_hospital_reception_regression.py` |
| `tests/test_vfarms_reception_transcript.py` |
| `tests/test_employee_playbook.py` |

Run legacy: `cd api && pytest -m legacy`

Default CI: `pytest` (LLM-first mocked tests only).