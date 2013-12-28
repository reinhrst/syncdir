usage:

sync.py srcdir dstdir

Will start by copying all files from srcdir to dstdir, and then incrementally copy all changes.

Works on OSX, but through watchdog should work on all systems supporting python

First install watchdog: https://github.com/gorakhargosh/watchdog
