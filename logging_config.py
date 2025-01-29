import logging
import logging.config
import yaml
import os
from pathlib import Path

# Default logging configuration
DEFAULT_CONFIG = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'standard': {
            'format': '%(asctime)s [%(levelname)s] %(name)s: %(message)s'
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'level': 'INFO',
            'formatter': 'standard',
            'stream': 'ext://sys.stdout'
        },
        'file': {
            'class': 'logging.FileHandler',
            'level': 'DEBUG',
            'formatter': 'standard',
            'filename': 'app.log',
            'mode': 'a'
        }
    },
    'loggers': {
        'sales_targeting': {
            'level': 'INFO',
            'handlers': ['console', 'file'],
            'propagate': False
        },
        'comparison_system': {
            'level': 'INFO',
            'handlers': ['console', 'file'],
            'propagate': False
        }
    }
}


def setup_logging(config_path='logging_config.yml'):
    """
    Set up logging configuration. If config file exists, use it.
    Otherwise, use default configuration.

    Args:
        config_path (str): Path to YAML configuration file
    """
    config_path = Path(config_path)

    if config_path.exists():
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)
        logging.config.dictConfig(config)
    else:
        # Save default config for user reference
        with open(config_path, 'w') as f:
            yaml.dump(DEFAULT_CONFIG, f, default_flow_style=False)
        logging.config.dictConfig(DEFAULT_CONFIG)


def get_logger(name):
    """
    Get a logger instance for the specified module/component.

    Args:
        name (str): Name of the module/component

    Returns:
        logging.Logger: Configured logger instance
    """
    return logging.getLogger(name)