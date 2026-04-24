Create a home assitant integration reading sensors from celsiview API into home assistant.
A Few things to consider:
* The Celsiview sensors uploads their data in bulk a few times per day, rather than live streaming.
* The documentation of the API is a available in a HTML document in this folder
* Another service reading the API can be found here: https://gitlab.com/modvion/tcc/churnbabychurn/importer-celsiview
* What sensors are actually imported must be selected by the user. Importing all sensor is far too much data.
* Make the API poll rate configurable, with a default at 15 minutes
* Give it a nice readme
* Consider that the integration will be mirrorerd on github and can be added through HACS. It will also be installable using GPM