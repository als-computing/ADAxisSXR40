# boot/ — needs the IOC (ours or Damon's)

Reads the console log slice since the last procServ start: capability audit, autosave
`N of N PV's connected`, exactly the expected write errors, no warnings or crash
signatures. Checks the autosave save file is complete and covers every plugin, that one
IOC and one pvAccess server exist, and that the start guard refuses a second IOC.
