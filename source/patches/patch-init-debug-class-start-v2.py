#!/usr/bin/env python3
"""
TEMPORARY diagnostic patch, not meant to ship: adds LOG(ERROR) tracing to
do_class_start() and Service::StartIfNotDisabled() in system/core/init, to find out
directly why `class_start hal` never attempts any of its 22 services under this port's
own vendor.img, despite ruling out every likely cause from source alone: the persist.init.dont_start_class.hal kill switch (confirmed unset), the
`disabled` .rc keyword (none of the 22 files have it), an explicit `disable` command
(none exist anywhere in the init tree), and a parse-time error (all 75 vendor .rc files,
composer's included, parse clean).

Logs, for every do_class_start() call: the class name requested, how many services in
ServiceList actually have that classname registered at the moment class_start runs, and
for each, its raw flags_ bitmask both before and after StartIfNotDisabled() -- this
directly answers the two live open questions: (1) does the "hal" class even have any
member services registered in ServiceList by the time class_start fires, and (2) if so,
is SVC_DISABLED (0x2) already set on them, and does it change.
"""
import sys

HADK = sys.argv[1] if len(sys.argv) > 1 else '.'
edits = 0


def patch(path, replacements):
    global edits
    full = HADK + '/' + path
    src = open(full).read()
    for old, new in replacements:
        n = src.count(old)
        if n != 1:
            print('ANCHOR MISS in %s: %d occurrences of:\n%s' % (path, n, old))
            sys.exit(1)
        src = src.replace(old, new)
    open(full, 'w').write(src)
    edits += 1
    print('patched %s' % path)


patch('system/core/init/builtins.cpp', [
    ("""static Result<void> do_class_start(const BuiltinArguments& args) {
    // Do not start a class if it has a property persist.dont_start_class.CLASS set to 1.
    if (android::base::GetBoolProperty("persist.init.dont_start_class." + args[1], false))
        return {};
    // Starting a class does not start services which are explicitly disabled.
    // They must  be started individually.
    for (const auto& service : ServiceList::GetInstance()) {
        if (service->classnames().count(args[1])) {
            if (auto result = service->StartIfNotDisabled(); !result.ok()) {
                LOG(ERROR) << "Could not start service '" << service->name()
                           << "' as part of class '" << args[1] << "': " << result.error();
            }
        }
    }
    return {};
}""",
     """static Result<void> do_class_start(const BuiltinArguments& args) {
    // Do not start a class if it has a property persist.dont_start_class.CLASS set to 1.
    if (android::base::GetBoolProperty("persist.init.dont_start_class." + args[1], false)) {
        LOG(ERROR) << "HYBRISDEBUG class_start '" << args[1] << "': dont_start_class set, skipping";
        return {};
    }
    // Starting a class does not start services which are explicitly disabled.
    // They must  be started individually.
    int hybrisdebug_count = 0;
    for (const auto& service : ServiceList::GetInstance()) {
        if (service->classnames().count(args[1])) {
            hybrisdebug_count++;
            LOG(ERROR) << "HYBRISDEBUG class_start '" << args[1] << "': found service '"
                       << service->name() << "' flags=0x" << std::hex << service->flags()
                       << std::dec;
            if (auto result = service->StartIfNotDisabled(); !result.ok()) {
                LOG(ERROR) << "Could not start service '" << service->name()
                           << "' as part of class '" << args[1] << "': " << result.error();
            } else {
                LOG(ERROR) << "HYBRISDEBUG class_start '" << args[1] << "': StartIfNotDisabled('"
                           << service->name() << "') returned ok, flags now=0x" << std::hex
                           << service->flags() << std::dec;
            }
        }
    }
    LOG(ERROR) << "HYBRISDEBUG class_start '" << args[1] << "': " << hybrisdebug_count
               << " services matched this classname";
    return {};
}"""),
])
