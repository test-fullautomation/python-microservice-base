# robot-gen

Adds **Robot Resources** to the Developer tab's Build group: generate one
Robot Framework `.resource` per service from a folder of `.proto` files.
The generator itself is the shell's (`_runRobotGen()` in `web/js/app.js`,
`POST /api/scaffold/robot` on the bridge); this plugin only contributes the
command, so disabling it removes the button.