"""Configuration loader for iMessage parser.

Loads configuration from ~/.imessage-parser/config.json with fallback to
the default configuration file. Handles initialization, validation, and
provides convenient access to configuration values.
"""

import json
import os
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional


# Configuration paths
DEFAULT_CONFIG_PATH = Path(__file__).parent.parent.parent / "config" / "default_config.json"
USER_CONFIG_DIR = Path.home() / ".imessage-parser"
USER_CONFIG_PATH = USER_CONFIG_DIR / "config.json"

# Required top-level keys for validation
REQUIRED_KEYS = {
    "spam_threshold",
    "whitelist",
    "blacklist",
    "session_gap_seconds",
    "dormancy_threshold_days",
    "db_path",
    "spam_weights",
    "spam_patterns",
    "transient_thresholds",
    "tapback_only_thresholds",
    "automated_regular_thresholds",
    "time_windows",
    "importance_weights",
}


class ConfigError(Exception):
    """Raised when configuration loading or validation fails."""
    pass


class Config:
    """Configuration manager for iMessage parser.

    Loads configuration from user config file or default config file,
    with automatic initialization and validation.

    Attributes:
        data: The loaded configuration dictionary.
        config_path: Path to the configuration file that was loaded.
    """

    def __init__(self, config_path: Optional[str] = None):
        """Initialize configuration by loading from user or default config.

        Args:
            config_path: Optional path to user config file.
                        Defaults to ~/.imessage-parser/config.json
        """
        self.data: Dict[str, Any] = {}
        self.user_config_path = Path(config_path) if config_path else USER_CONFIG_PATH
        self.config_path: Path = self.user_config_path
        self._load()

    def _ensure_user_config_exists(self) -> None:
        """Create user config directory and copy default config if needed."""
        config_dir = self.user_config_path.parent
        if not config_dir.exists():
            try:
                config_dir.mkdir(parents=True, exist_ok=True)
            except OSError as e:
                raise ConfigError(f"Failed to create config directory {config_dir}: {e}")

        if not self.user_config_path.exists():
            if not DEFAULT_CONFIG_PATH.exists():
                raise ConfigError(f"Default config not found at {DEFAULT_CONFIG_PATH}")

            try:
                shutil.copy2(DEFAULT_CONFIG_PATH, self.user_config_path)
            except OSError as e:
                raise ConfigError(f"Failed to copy default config to {self.user_config_path}: {e}")

    def _load_json(self, path: Path) -> Dict[str, Any]:
        """Load and parse JSON configuration file.

        Args:
            path: Path to the JSON configuration file.

        Returns:
            Parsed configuration dictionary.

        Raises:
            ConfigError: If file cannot be read or parsed.
        """
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except FileNotFoundError:
            raise ConfigError(f"Configuration file not found: {path}")
        except json.JSONDecodeError as e:
            raise ConfigError(f"Invalid JSON in {path}: {e}")
        except OSError as e:
            raise ConfigError(f"Failed to read {path}: {e}")

    def _validate_schema(self, config: Dict[str, Any]) -> None:
        """Validate that all required keys are present in the configuration.

        Args:
            config: Configuration dictionary to validate.

        Raises:
            ConfigError: If required keys are missing.
        """
        missing_keys = REQUIRED_KEYS - set(config.keys())
        if missing_keys:
            raise ConfigError(f"Missing required configuration keys: {', '.join(sorted(missing_keys))}")

    def _expand_paths(self) -> None:
        """Expand ~ in db_path to the user's home directory."""
        if "db_path" in self.data and isinstance(self.data["db_path"], str):
            self.data["db_path"] = str(Path(self.data["db_path"]).expanduser())

    def _load(self) -> None:
        """Load configuration from user config or default config."""
        # Ensure user config exists (create from default if needed)
        self._ensure_user_config_exists()

        # Try to load user config first
        try:
            self.data = self._load_json(self.user_config_path)
            self.config_path = self.user_config_path
        except ConfigError:
            # Fall back to default config
            self.data = self._load_json(DEFAULT_CONFIG_PATH)
            self.config_path = DEFAULT_CONFIG_PATH

        # Validate and process
        self._validate_schema(self.data)
        self._expand_paths()

    def get(self, key: str, default: Any = None) -> Any:
        """Get a top-level configuration value.

        Args:
            key: Configuration key to retrieve.
            default: Default value if key is not found.

        Returns:
            Configuration value or default.
        """
        return self.data.get(key, default)

    def get_nested(self, *keys: str, default: Any = None) -> Any:
        """Get a nested configuration value.

        Args:
            *keys: Sequence of keys to traverse (e.g., 'spam_weights', 'zero_reply_ever').
            default: Default value if path is not found.

        Returns:
            Configuration value or default.

        Example:
            >>> config.get_nested('spam_weights', 'zero_reply_ever')
            0.6
        """
        value = self.data
        for key in keys:
            if isinstance(value, dict):
                value = value.get(key)
                if value is None:
                    return default
            else:
                return default
        return value

    def set(self, key: str, value: Any) -> None:
        """Set configuration value and persist to user config.

        Args:
            key: Configuration key (supports nested keys with dots)
            value: Value to set
        """
        keys = key.split('.')
        config = self.data
        for k in keys[:-1]:
            if k not in config:
                config[k] = {}
            config = config[k]
        config[keys[-1]] = value

        # Persist to user config
        self.save()

    def save(self) -> None:
        """Save current configuration to user config file."""
        try:
            self.user_config_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.user_config_path, 'w', encoding='utf-8') as f:
                json.dump(self.data, f, indent=2)
        except OSError as e:
            raise ConfigError(f"Failed to save config to {self.user_config_path}: {e}")

    def add_to_whitelist(self, contact_id: str) -> None:
        """Add contact to spam filter whitelist.

        Args:
            contact_id: Phone number or email to whitelist
        """
        whitelist = self.get('whitelist', [])
        if contact_id not in whitelist:
            whitelist.append(contact_id)
            self.set('whitelist', whitelist)

    def add_to_blacklist(self, contact_id: str) -> None:
        """Add contact to spam filter blacklist.

        Args:
            contact_id: Phone number or email to blacklist
        """
        blacklist = self.get('blacklist', [])
        if contact_id not in blacklist:
            blacklist.append(contact_id)
            self.set('blacklist', blacklist)

    def is_whitelisted(self, contact_id: str) -> bool:
        """Check if contact is whitelisted.

        Args:
            contact_id: Phone number or email

        Returns:
            True if whitelisted
        """
        return contact_id in self.get('whitelist', [])

    def is_blacklisted(self, contact_id: str) -> bool:
        """Check if contact is blacklisted.

        Args:
            contact_id: Phone number or email

        Returns:
            True if blacklisted
        """
        return contact_id in self.get('blacklist', [])

    @property
    def spam_threshold(self) -> float:
        """Get spam classification threshold."""
        return self.data["spam_threshold"]

    @property
    def whitelist(self) -> List[str]:
        """Get list of whitelisted contacts."""
        return self.data["whitelist"]

    @property
    def blacklist(self) -> List[str]:
        """Get list of blacklisted contacts."""
        return self.data["blacklist"]

    @property
    def db_path(self) -> str:
        """Get expanded path to iMessage database."""
        return self.data["db_path"]

    @property
    def session_gap_seconds(self) -> int:
        """Get session gap threshold in seconds."""
        return self.data["session_gap_seconds"]

    @property
    def dormancy_threshold_days(self) -> int:
        """Get dormancy threshold in days."""
        return self.data["dormancy_threshold_days"]

    @property
    def spam_weights(self) -> Dict[str, float]:
        """Get spam detection weights."""
        return self.data["spam_weights"]

    @property
    def spam_patterns(self) -> List[str]:
        """Get spam detection regex patterns."""
        return self.data["spam_patterns"]

    def reload(self) -> None:
        """Reload configuration from disk."""
        self._load()

    def __repr__(self) -> str:
        """Return string representation of Config object."""
        return f"Config(path={self.config_path}, keys={len(self.data)})"


# Global config instance
_config_instance: Optional[Config] = None


def get_config(config_path: Optional[str] = None) -> Config:
    """Get the global configuration instance.

    Creates and loads the configuration on first call.

    Args:
        config_path: Optional path to user config file

    Returns:
        Global Config instance
    """
    global _config_instance
    if _config_instance is None:
        _config_instance = Config(config_path)
    return _config_instance


def reload_config(config_path: Optional[str] = None) -> Config:
    """Reload the global configuration from disk.

    Args:
        config_path: Optional path to user config file

    Returns:
        Reloaded global Config instance
    """
    global _config_instance
    _config_instance = Config(config_path)
    return _config_instance
