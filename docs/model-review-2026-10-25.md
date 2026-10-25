# Model review — 2026-10-25

## Decision

Keep the existing OpenAI routing: the product's persisted `gpt-6-sol` id
already selects `gpt-6.1-sol` through the OpenAI client's API-id mapping. Production confirms
the configured id and access to GPT-6.1 Sol, GPT-6 Astra and GPT-6 Luna.
Do not replace affordable routes with Astra or change reasoning effort.

Send DeepSeek Flash requests using the documented `deepseek-flash` API id,
currently DeepSeek-V4.1-Flash-1017. Keep `deepseek-v4-flash` as the internal
product/accounting id to preserve permissions, reservations and usage history.
Accept either id at the client boundary. Keep DeepSeek V4 Pro on its existing
route. Return complete `reasoning_content`, including an empty value, with
assistant tool-call frames when continuing a thinking conversation.

DeepSeek already routes the old Flash alias to V4.1-Flash-1017. This release
removes reliance on that temporary alias and fixes thinking/tool compatibility;
it does not claim a newly activated quality improvement over yesterday's calls.
The provider reports improvements over earlier V4.1 in its October 17 release.
The bounded checks below confirm compatibility, not a comprehensive quality eval.

## Budget

Official prices per million tokens, USD, checked October 25:

| Model | Uncached input | Output | Cached input |
| --- | ---: | ---: | ---: |
| GPT-6.1 Sol | 2.00 | 10.00 | 0.10 |
| GPT-6 Sol | 2.00 | 10.00 | 0.20 |
| DeepSeek Flash, off-peak | 0.15 | 0.60 | 0.003 |
| DeepSeek Flash, peak | 0.30 | 1.20 | 0.006 |

DeepSeek peak hours are 01:00–04:00 and 06:00–10:00 UTC on weekdays,
excluding Chinese public holidays. Legacy Flash aliases have the same price
as the canonical id. Therefore this compatibility change does not increase
per-token provider costs. Product quotas, multipliers, tariff prices, output
caps, stronger-model routes and provider settings remain unchanged.

## Validation

- Five regression cases cover both Flash ids, unchanged accounting/output cap,
  thinking/tool continuation with empty and nonempty reasoning, and Pro routing.
  Four failed before the fix; all five pass afterward.
- Focused provider, routing and budget suite: 238 passed.
- Complete backend suite: 920 passed, exit code 0. Existing dependency
  deprecation warnings remain; no test failures.
- Production credentials and model listings confirm both new model ids are
  available. Direct bounded arithmetic checks returned the expected total of
  138 with GPT-6.1 Sol and streaming DeepSeek Flash.
- A real DeepSeek thinking/tool conversation completed two provider calls,
  returning the fixture's total of 138; 645 input tokens and 40 output tokens,
  less than $0.00025 even at the documented peak rate.
- Deployment includes a further end-to-end check through the actual application
  DeepSeek client with a fixture tool and canonical provider/stable billing ids.
  The release script restores the prior backend if this check fails. No real
  user conversation, wallet or workspace is used for the fixture.

## Official sources

- [OpenAI model catalog](https://developers.openai.com/api/docs/models)
- [GPT-6.1 Sol capabilities and pricing](https://developers.openai.com/api/docs/models/gpt-6.1-sol)
- [GPT-6 Sol pricing](https://developers.openai.com/api/docs/models/gpt-6-sol)
- [OpenAI pricing](https://developers.openai.com/api/docs/pricing)
- [GPT-6 Astra migration quickstart](https://developers.openai.com/api/docs/guides/latest-model/gpt-6-astra.md#migration-quickstart)
- [DeepSeek current models, legacy aliases and pricing](https://api-docs.deepseek.com/quick_start/pricing/)
- [DeepSeek October 17 update](https://api-docs.deepseek.com/updates/)
- [DeepSeek thinking/tool continuation requirements](https://api-docs.deepseek.com/guides/thinking_mode/)
