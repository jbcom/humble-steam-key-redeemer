# API reference

The package is usable as a library as well as a command-line tool.

```{toctree}
:maxdepth: 1

core
humble
steam
settings
```

## Example

```python
from humble_steam_key_redeemer import RedeemerStore, Settings
from humble_steam_key_redeemer.core import RedemptionEngine
from humble_steam_key_redeemer.steam import VendorFabricSteamGateway

settings = Settings()
store = RedeemerStore(settings.database_path)

gateway = VendorFabricSteamGateway(settings)
if not gateway.restore():
    raise SystemExit("No saved Steam session; run `hskr redeem` once to sign in.")

engine = RedemptionEngine(store, gateway)
plan = engine.plan(store.pending_keys())

for entry in plan.uncertain:
    print(entry.record.human_name, "->", entry.decision.app_name, entry.decision.score)
```
