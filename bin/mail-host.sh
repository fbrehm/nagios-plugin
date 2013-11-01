#!/bin/bash

PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
export PATH

FROM="PB Monitoring <monitoring@profitbricks.com>"
if [ -n "${ICINGA_ADMINEMAIL}" ] ; then
    FROM="${ICINGA_ADMINEMAIL}"
fi

SUBJECT="** ${ICINGA_NOTIFICATIONTYPE} Host Alert: ${ICINGA_HOSTNAME} is ${ICINGA_HOSTSTATE}"

TO="${ICINGA_CONTACTEMAIL}"

BODY=$(cat <<ENDE
***** Nagios *****

Notification Type: ${ICINGA_NOTIFICATIONTYPE}

Host:    ${ICINGA_HOSTALIAS}
Address: ${ICINGA_HOSTADDRESS}
State:   ${ICINGA_HOSTSTATE}

Notification-Number: ${ICINGA_HOSTNOTIFICATIONNUMBER}

Date/Time: ${ICINGA_LONGDATETIME}

Info: ${ICINGA_HOSTOUTPUT}
ENDE
)
printf "${BODY}" | mailx -r "${FROM}" -s "${SUBJECT}" "${TO}"

# vim: ts=4 expandtab
