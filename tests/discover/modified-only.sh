#!/bin/bash

. /usr/share/beakerlib/beakerlib.sh || exit 1

rlJournalStart
    rlPhaseStartSetup
        rlRun 'set -o pipefail'
    rlPhaseEnd

    rlPhaseStartTest 'All steps'
        rlRun 'tmt run -dv discover --how fmf --ref 8329db0421e9 --modified-only --reference-ref 8329db0421e9^ \
            | tee output'
    rlPhaseEnd

    rlPhaseStartCleanup
        rlRun 'rm -f output' 0 'Removing tmp file'
    rlPhaseEnd
rlJournalEnd
