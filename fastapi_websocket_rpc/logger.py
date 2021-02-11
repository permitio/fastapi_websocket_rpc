import logging
from logging import config
from logging.config import dictConfig
import os
from enum import Enum
from typing import NewType

ENV_VAR = "WS_RPC_LOGGING"


class LoggingModes(Enum):
    # don't produce logs
    NO_LOGS = 0
    # Log alongside uvicorn
    UVICORN = 1
    # Simple log calls (no config)
    SIMPLE = 2
    # log via the loguru module
    LOGURU = 3


LoggingMode = NewType('LoggingMode', LoggingModes)


class LoggingConfig:

    def __init__(self) -> None:
        self._mode = None

    config_template = {
        "version": 1,
        "disable_existing_loggers": True,
        "formatters": {
            "default": {
                "()": "uvicorn.logging.DefaultFormatter",
                "fmt": "%(levelprefix)s %(asctime)s %(message)s",
                "datefmt": "%Y-%m-%d %H:%M:%S",
            },
        },
        "handlers": {
            "default": {
                "formatter": "default",
                "class": "logging.StreamHandler",
            },
        },
        "loggers": {}
    }



    UVICORN_LOGGERS = {
        'uvicorn.error': {
            'propagate': False,
            'handlers': ['default'],
        },
        "fastapi_ws_rpc": {"handlers": ["default"], 'propagate': False, 'level': logging.INFO},
    }

    def get_mode(self):
        # if no one set the mode - set default from ENV or hardcoded default
        if self._mode is None:
            mode = LoggingModes.__members__.get(os.environ.get(ENV_VAR, "").upper(), LoggingModes.SIMPLE)
            self.set_mode(mode)
        return self._mode

    def set_mode(self, mode: LoggingMode = LoggingModes.UVICORN, level= logging.INFO):
        """
        Configure logging. this method calls 'logging.config.dictConfig()' to enable quick setup of logging.
        Call this method before starting the app.
        For more advanced cases use 'logging.config' directly (loggers used by this library are all nested under "fastapi_ws_rpc" logger name)

        Args:
            mode (LoggingMode, optional): The mode to set logging to. Defaults to LoggingModes.UVICORN.
        """
        self._mode = mode
        logging_config = self.config_template.copy()
        # add logs beside uvicorn
        if mode == LoggingModes.UVICORN:
            logging_config["loggers"] = self.UVICORN_LOGGERS.copy()
            logging_config["loggers"]["fastapi_ws_rpc"]["level"] = level
            dictConfig(logging_config)
        elif mode == LoggingModes.SIMPLE:
            pass
        elif mode == LoggingModes.LOGURU:
            pass
        # no logs
        else:
            logging_config["loggers"] = {}
            dictConfig(logging_config)


# Singelton for logging configuration
logging_config = LoggingConfig()


def get_logger(name):
    """
    Get a logger object to log with..
    Called by inner modules for logging. 
    """
    mode = logging_config.get_mode()
    # logging through loguru
    if mode == LoggingModes.LOGURU:
        from loguru import logger
    else:
        # regular python logging
        logger = logging.getLogger(f"fastapi_ws_rpc.{name}")

    return logger
