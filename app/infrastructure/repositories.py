from __future__ import annotations

from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.application.interfaces import PluginManifest, ThemeManifest
from app.domain.entities import DeviceState
from app.domain.events import DomainEvent
from app.domain.value_objects import utc_now
from app.infrastructure.models import CurrentStateModel, PluginModel, SettingModel, StateSnapshotModel, ThemeModel


class SqlAlchemySettingsRepository:
    def __init__(self, session_factory: sessionmaker) -> None:
        self._session_factory = session_factory

    def get(self, key: str, default: str | None = None) -> str | None:
        with self._session_factory() as session:
            model = session.get(SettingModel, key)
            return model.value if model else default

    def set(self, key: str, value: str) -> None:
        with self._session_factory.begin() as session:
            model = session.get(SettingModel, key)
            if model is None:
                model = SettingModel(key=key, value=value)
                session.add(model)
            else:
                model.value = value

    def get_prefix(self, prefix: str) -> dict[str, str]:
        with self._session_factory() as session:
            query = select(SettingModel).where(SettingModel.key.startswith(prefix))
            items = session.execute(query).scalars().all()
            return {
                item.key.removeprefix(prefix): item.value
                for item in items
            }


class SqlAlchemyStateRepository:
    def __init__(self, session_factory: sessionmaker) -> None:
        self._session_factory = session_factory

    def load_state(self) -> DeviceState | None:
        with self._session_factory() as session:
            current = session.get(CurrentStateModel, 1)
            if current is None:
                return None
            return DeviceState.from_dict(current.payload)

    def load_or_create(self, pet_name: str) -> DeviceState:
        state = self.load_state()
        if state is not None:
            return state

        initial_state = DeviceState.create(pet_name)
        self.save_state(
            state=initial_state,
            source="bootstrap",
            command_id=None,
            events=[DomainEvent(event_type="state_bootstrapped", payload={"pet_name": pet_name})],
        )
        return initial_state

    def save_state(
        self,
        state: DeviceState,
        source: str,
        command_id: str | None,
        events: list[DomainEvent],
    ) -> int:
        now = utc_now()

        with self._session_factory.begin() as session:
            current = session.get(CurrentStateModel, 1)
            if current is not None and state.state_version <= current.state_version:
                state.bump_version()

            payload = state.to_dict()

            if current is None:
                current = CurrentStateModel(
                    id=1,
                    schema_version=state.schema_version,
                    state_version=state.state_version,
                    payload=payload,
                    updated_at=now,
                )
                session.add(current)
            else:
                current.schema_version = state.schema_version
                current.state_version = state.state_version
                current.payload = payload
                current.updated_at = now

            snapshot = StateSnapshotModel(
                snapshot_id=str(uuid4()),
                schema_version=state.schema_version,
                state_version=state.state_version,
                source=source,
                command_id=command_id,
                payload=payload,
                events=[event.to_dict() for event in events],
                created_at=now,
            )
            session.add(snapshot)

        return state.state_version

    def restore_state(self, state: DeviceState, source: str) -> int:
        with self._session_factory() as session:
            current = session.get(CurrentStateModel, 1)
            if current is not None:
                state.state_version = max(current.state_version + 1, state.state_version)

        return self.save_state(
            state=state,
            source=source,
            command_id=None,
            events=[DomainEvent(event_type="state_imported", payload={"source": source})],
        )

    def get_state_version(self) -> int:
        with self._session_factory() as session:
            current = session.get(CurrentStateModel, 1)
            return current.state_version if current else 0


class SqlAlchemyPluginRepository:
    def __init__(self, session_factory: sessionmaker) -> None:
        self._session_factory = session_factory

    def upsert_manifests(self, manifests: list[PluginManifest]) -> None:
        now = utc_now()
        with self._session_factory.begin() as session:
            known_ids = {manifest.plugin_id for manifest in manifests}
            existing_rows = session.execute(select(PluginModel)).scalars().all()
            for row in existing_rows:
                if row.plugin_id not in known_ids:
                    session.delete(row)

            for manifest in manifests:
                model = session.get(PluginModel, manifest.plugin_id)
                if model is None:
                    model = PluginModel(
                        plugin_id=manifest.plugin_id,
                        name=manifest.name,
                        version=manifest.version,
                        description=manifest.description,
                        enabled=False,
                        manifest=manifest.to_dict(),
                        updated_at=now,
                    )
                    session.add(model)
                else:
                    model.name = manifest.name
                    model.version = manifest.version
                    model.description = manifest.description
                    model.manifest = manifest.to_dict()
                    model.updated_at = now

    def list_plugins(self) -> list[dict[str, Any]]:
        with self._session_factory() as session:
            rows = session.execute(select(PluginModel).order_by(PluginModel.plugin_id.asc())).scalars().all()
            return [
                {
                    "plugin_id": row.plugin_id,
                    "name": row.name,
                    "version": row.version,
                    "description": row.description,
                    "enabled": row.enabled,
                    "manifest": row.manifest,
                    "updated_at": row.updated_at.isoformat(),
                }
                for row in rows
            ]

    def set_enabled(self, plugin_id: str, enabled: bool) -> None:
        with self._session_factory.begin() as session:
            model = session.get(PluginModel, plugin_id)
            if model is None:
                raise ValueError(f"Plugin '{plugin_id}' does not exist.")
            model.enabled = enabled
            model.updated_at = utc_now()

    def list_enabled_ids(self) -> list[str]:
        with self._session_factory() as session:
            rows = session.execute(select(PluginModel).where(PluginModel.enabled.is_(True))).scalars().all()
            return sorted(row.plugin_id for row in rows)


class SqlAlchemyThemeRepository:
    def __init__(self, session_factory: sessionmaker) -> None:
        self._session_factory = session_factory

    def upsert_manifests(self, manifests: list[ThemeManifest]) -> None:
        now = utc_now()
        with self._session_factory.begin() as session:
            for manifest in manifests:
                model = session.get(ThemeModel, manifest.theme_id)
                if model is None:
                    model = ThemeModel(
                        theme_id=manifest.theme_id,
                        name=manifest.name,
                        version=manifest.version,
                        description=manifest.description,
                        active=False,
                        manifest=manifest.to_dict(),
                        updated_at=now,
                    )
                    session.add(model)
                else:
                    model.name = manifest.name
                    model.version = manifest.version
                    model.description = manifest.description
                    model.manifest = manifest.to_dict()
                    model.updated_at = now

    def list_themes(self) -> list[dict[str, Any]]:
        with self._session_factory() as session:
            rows = session.execute(select(ThemeModel).order_by(ThemeModel.theme_id.asc())).scalars().all()
            return [
                {
                    "theme_id": row.theme_id,
                    "name": row.name,
                    "version": row.version,
                    "description": row.description,
                    "active": row.active,
                    "manifest": row.manifest,
                    "updated_at": row.updated_at.isoformat(),
                }
                for row in rows
            ]

    def activate(self, theme_id: str) -> None:
        with self._session_factory.begin() as session:
            all_themes = session.execute(select(ThemeModel)).scalars().all()
            found = False
            for theme in all_themes:
                is_active = theme.theme_id == theme_id
                if is_active:
                    found = True
                theme.active = is_active
                theme.updated_at = utc_now()
            if not found:
                raise ValueError(f"Theme '{theme_id}' does not exist.")

    def get_active_id(self) -> str | None:
        with self._session_factory() as session:
            theme = session.execute(select(ThemeModel).where(ThemeModel.active.is_(True))).scalars().first()
            return theme.theme_id if theme else None
