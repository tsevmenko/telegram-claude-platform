# HOT memory — full rolling 24h journal

_Full conversation log. NOT loaded into session context._
_Written after every gateway turn via `memory/hot.py` with `fcntl.LOCK_EX`._
_Entries older than 24h or beyond 40-entry cap are compressed to WARM by `trim-hot.sh`._
