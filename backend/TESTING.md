# Backend test gates

Run the hermetic release gate without credentials or external services:

```sh
python -m pytest tests -m "not integration and not requires_db"
```

Run database-backed tests only against an isolated, migrated test database:

```sh
python -m pytest tests -m requires_db
```

Provider integration tests are separate because they may exercise external
transport behavior:

```sh
python -m pytest tests -m integration
```
