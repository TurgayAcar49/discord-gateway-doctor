# Failure classes

Hermes 0.18 and later fail closed. A Discord adapter with no user allowlist, no role allowlist, no channel allowlist, and no explicit allow-all flag connects, then denies every inbound message.

Message Content Intent is different. Hermes always requests it. If the Developer Portal toggle is off, Discord rejects the WebSocket and the bot stays offline. Server Members Intent is requested only when `DISCORD_ALLOWED_ROLES` is set or `DISCORD_ALLOWED_USERS` contains usernames.

| Code | What it means |
| --- | --- |
| `missing_hermes_home` | The directory passed to the doctor does not exist. |
| `missing_token` | `DISCORD_BOT_TOKEN` is missing, so the gateway cannot log in. |
| `unexpected_token_shape` | A value is set, but it does not have the three-part bot-token shape. |
| `token_present` | A bot-shaped token is stored. This does not prove Discord will accept it. |
| `no_access_policy` | Nothing authorizes inbound users. The bot can look online and still ignore everyone. |
| `access_policy_present` | At least one allowlist or allow-all flag is set. |
| `username_allowlist` | A user entry is not a 17-20 digit snowflake. Resolution needs Server Members Intent, and only the real username matches. |
| `invalid_id_list` | A role or channel entry is not a snowflake. Names are ignored. |
| `allow_all_users` | `DISCORD_ALLOW_ALL_USERS` or `GATEWAY_ALLOW_ALL_USERS` is true. |
| `members_intent_required` | Roles or usernames are in the policy, so Server Members Intent must be on. |
| `privileged_intents_rejected` | `gateway.log` already shows Discord closing the socket for intents. |
| `no_access_policy_logged` | The log recorded the fail-closed warning. Level `info` means the files now have a policy and the process is stale. |
| `token_rejected_logged` | The log shows Discord refusing the token. |
| `token_rejected` | Live `GET /users/@me` returned 401. |
| `token_valid` | Live `GET /users/@me` returned the bot user. |
| `token_id_mismatch` | The id baked into the token differs from `/users/@me`. |
| `message_content_intent_off` | Application flags lack both Message Content bits (`1 << 18` and `1 << 19`). |
| `message_content_intent_on` | One of those bits is set. |
| `server_members_intent_off` | The policy needs members, and neither members bit (`1 << 14`, `1 << 15`) is set. |
| `server_members_intent_on` | The members intent bit is set. |
| `discord_unreachable` | The live call could not open a connection. |
| `discord_unexpected` | Discord returned something other than 200 or 401 for `/users/@me`. |
| `application_unreadable` | The token worked, but `/applications/@me` did not, so intent flags were skipped. |

Portal path for both privileged intents: Developer Portal → application → Bot → Privileged Gateway Intents → Save Changes. Then `hermes gateway restart`.
