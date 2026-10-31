# `pipeline json` output

`pipeline json` prints one line of JSON and never uses the network. It always prints valid JSON, even
with an invalid configuration or a damaged database, so the bar can always parse it. In those cases
`status` is `"error"` and the exit code is 1.

`schema_version` changes when an existing field changes. Adding a field does not change it.

## Top level

| Field | Type | Meaning |
|---|---|---|
| `schema_version` | integer | Currently `1` |
| `generated_at` | integer | Unix time of this report |
| `status` | string | `fresh`, `stale`, `no_data` or `error` |
| `error` | string or null | Reason when `status` is `error` |
| `currency` | string or null | Configured currency |
| `timezone` | string or null | Configured time zone |
| `bar` | object | Data for the compact bar element |
| `groups` | array | `crypto`, `indices` and `stocks`, each with `id`, `title`, `series_label`, `change_label` and `items` |
| `providers` | array | Provider status, attribution and call counts |

`status` ignores `unavailable` rows: indices and stocks without a provider do not make the report
stale.

`series_label` and `change_label` name the periods of the sparkline and of the variation, such as
`7 d` and `24 h`. They are `null` for a group without a provider.

## Rows in `groups[].items`

Every row has every field, with `null` when a value does not apply.

| Field | Meaning |
|---|---|
| `symbol`, `name`, `short_name` | Identifiers and labels |
| `asset_class` | `crypto`, `index` or `stock` |
| `state` | See below |
| `state_label` | Text for `state`; for `fresh`, the data age |
| `stale` | `true` when `state` is `stale` or `held` |
| `reason` | Why the row is not `fresh` |
| `provider` | Provider id of the data |
| `price`, `price_text` | Value, and its `es_ES` text |
| `compact_text` | Short value for the bar |
| `currency` | `null` for indices, which are points |
| `change_percent`, `change_text` | Variation, and its `es_ES` text |
| `direction` | `up`, `down`, `flat` or `null` |
| `kind` | `live` or `close` |
| `price_time`, `fetched_at` | Unix times of the price and of its download |
| `age_seconds`, `age_text` | Age of the price |
| `series` | Up to 48 values for the sparkline, oldest first |
| `hold` | Details of a held price, or `null` |

### Row states

| `state` | Has a price | Meaning |
|---|---|---|
| `fresh` | yes | Recently refreshed |
| `stale` | yes | The last refresh failed, or the price is old. `reason` says which |
| `held` | yes | A new price jumped too far and was not applied. See `hold` |
| `no_data` | no | Never fetched, or more than 24 hours without a refresh |
| `unavailable` | no | No provider is configured for this row |

`hold` contains `rejected_price`, `rejected_price_text`, `jump_percent`, `since`, `since_text` and
`last_seen`.

## `bar`

`items` has one entry per configured symbol, with `symbol`, `label`, `value_text`, `change_text`,
`direction` and `state`. `value_text` is `—` when there is no price. `updated_at` is the latest
download time, and `tooltip` is ready to display.

## `providers`

Each entry has `id`, `name`, `attribution`, `calls_24h`, `last_attempt`, `cooldown_until`,
`cooldown_until_text`, `offline_streak`, `next_attempt_at` and `next_attempt_text`.

`calls_limit` and `calls_remaining` are `null` when the provider publishes no limit. `calls_24h`
counts requests that could have reached the server: DNS and connection failures are not included.
