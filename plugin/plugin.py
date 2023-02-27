# -*- coding: UTF-8 -*-

# InfoBarWeather by scriptmelvin
# https://github.com/scriptmelvin/enigma2-plugin-extensions-infobarweather
# License: GPL-2.0

VERSION = '0.18'

from . import _, _N, PLUGIN_PATH, PLUGIN_NAME
from Components.ActionMap import ActionMap
from Components.Button import Button
from Components.config import config, ConfigBoolean, ConfigInteger, ConfigSelection, ConfigSubsection, ConfigText, ConfigYesNo, getConfigListEntry
from Components.ConfigList import ConfigListScreen
from Components.Label import Label, MultiColorLabel
from Components.MenuList import MenuList
from Components.Pixmap import MultiPixmap, Pixmap
from Components.Sources.Boolean import Boolean
from enigma import eLabel, eListboxPythonMultiContent, ePoint, eSize, eTimer, gFont, RT_HALIGN_LEFT, RT_HALIGN_RIGHT, RT_VALIGN_CENTER
from Plugins.Plugin import PluginDescriptor
from Screens.InfoBar import InfoBar
from Screens.InfoBarGenerics import InfoBarEPG, InfoBarShowHide
from Screens.MessageBox import MessageBox
from Screens.Screen import Screen
from Screens.VirtualKeyBoard import VirtualKeyBoard
from skin import parseFont
from Tools.BoundFunction import boundFunction
from Tools.Directories import fileExists

import datetime
import json
import os
import sys
import threading
import time
import xml


try:
	from urllib.parse import quote
except ImportError:
	from urllib import quote


try:

	import treq

	class download:

		def __init__(self, url, outputfile):
			self.url = url
			self.outputfile = outputfile

		def start(self):
			outfile = open(self.outputfile, "wb")
			return treq.get(self.url, unbuffered=True).addCallback(treq.collect, outfile.write).addBoth(lambda _: outfile.close())

except ImportError:

	from Tools.Downloader import downloadWithProgress as download


setattr(config.plugins, PLUGIN_NAME, ConfigSubsection())
settings = getattr(config.plugins, PLUGIN_NAME)
settings.enabled = ConfigYesNo(True)
settings.position = ConfigSelection(choices=[("1", _("In infobar")), ("2", _("Above infobar")), ("3", _("Top of screen"))], default="1")
settings.locationid = ConfigInteger(0)
settings.locationlat = ConfigText()
settings.locationlon = ConfigText()
settings.locationname = ConfigText()
settings.displayas = ConfigText(fixed_size=False, visible_width=50)
settings.locationname2 = ConfigSelection([_("Press OK")])
settings.windSpeedUnit = ConfigSelection(choices=[("1", _("BFT")), ("2", _("m/s")), ("3", _("km/h")), ("4", _("mph"))], default="1")
settings.temperatureUnit = ConfigSelection(choices=[("1", _("°C")), ("2", _("°F"))], default="1")
settings.showregio = ConfigYesNo(True)
settings.showtime = ConfigYesNo(True)
settings.showsunriseset = ConfigYesNo(True)
settings.showhumidity = ConfigYesNo(True)
settings.showrain = ConfigYesNo(True)
settings.showrainforecast = ConfigYesNo(True)
settings.showwind = ConfigYesNo(True)
settings.showicon = ConfigYesNo(True)
settings.showtemperature = ConfigYesNo(True)
settings.showfeeltemperature = ConfigYesNo(True)
settings.showminmaxtemperature = ConfigYesNo(True)
settings.showuvindex = ConfigYesNo(True)
settings.showsunpower = ConfigYesNo(True)
settings.hasRain = ConfigBoolean()


jsonUrl = "https://forecast.buienradar.nl/2.0/forecast/%d"
rainForecastUrl = "https://gpsgadget.buienradar.nl/data/raintext/?lat=%g&lon=%g"
tmpdir = "/tmp/%s" % PLUGIN_NAME
jsonFile = "%s/weather.json" % tmpdir
rainFile = "%s/rainForecast.txt" % tmpdir

TAG = PLUGIN_NAME

extraImportPath = "/etc/enigma2"
importPathModified = False
if extraImportPath not in sys.path:
	sys.path.insert(1, extraImportPath)
	importPathModified = True
try:
	from infobarextra import InfoBarExtra
except ImportError:
	# for adding extra widgets, like room temperature:
	# put class def between cut marks in /etc/enigma2/infobarextra.py (and add an empty __init__.py there as well)
	# and modify at will
	# -----8<-----8<-----8<-----8<-----8<-----8<-----8<-----8<-----8<-----8<-----
	class InfoBarExtra(object):
		def __init__(self, session):
			pass # modify self.skin here
		def timerCB(self):
			pass # called every minute while infobar is shown, retrieve (use twisted.web or threads if doing I/O) and display values here
		def onShowHideInfoBar(self, shown):
			pass # retrieve (use twisted.web or threads if doing I/O) and display values here when shown == True
		def onShowHideSecondInfoBar(self, shown):
			pass
	# -----8<-----8<-----8<-----8<-----8<-----8<-----8<-----8<-----8<-----8<-----
if importPathModified:
	del(sys.path[1])


class InfoBarWeather(Screen, InfoBarExtra):

	RAIN = 1
	WEATHER = 2
	REST = 4
	ALL = RAIN | WEATHER | REST
	hasRainWidget = False
	windDirections = ["N", "NNO", "NO", "ONO", "O", "OZO", "ZO", "ZZO", "Z", "ZZW", "ZW", "WZW", "W", "WNW", "NW", "NNW" ]
	units = {"airpressure": " " + _("hPa"), "feeltemperature": "°", "groundtemperature": "°", "mintemperature": "°", "maxtemperature": "°", "humidity": "%", "precipitation": "%", "rainFallLast24Hour": " " + _("mm"), "rainFallLastHour": " " + _("mm"), "sunpower": " " + _("W/m²"), "temperature": "°", "visibility": " " + _("m"), "winddirectiondegrees": "°", "windgusts": " " + _("m/s"), "windspeedms": " " + _("m/s"), "beaufort": " " + _("BFT")}
	infoBarBackground = None
	secondInfoBarBackground = None
	lastUpdate = datetime.datetime.min
	updateInterval = 10 # minutes
	lastUpdateLock = threading.Lock()
	pos = {
		"notconfigured"            : ePoint(  10,  0),
		"regio"                    : ePoint(  10,  0),
		"time"                     : ePoint( 352,  0),
		"sunrise"                  : ePoint( 442,  0),
		"sunrisesetPixmap"         : ePoint( 530,  7),
		"sunset"                   : ePoint( 587,  0),
		"humidityPixmap"           : ePoint( 690,  7),
		"humidity"                 : ePoint( 718,  0),
		"precipitationPixmap"      : ePoint( 798,  7),
		"rainWidgets"              : ePoint( 818,  1),
		"precipitation"            : ePoint( 828,  0),
		"zero"                     : ePoint( 812, 30),
		"one"                      : ePoint( 836, 30),
		"two"                      : ePoint( 860, 30),
		"winddirectionMultiPixmap" : ePoint( 907,  7),
		"beaufort"                 : ePoint( 940,  0),
		"windspeedms"              : ePoint( 940,  0),
		"weatherPixmap"            : ePoint(1057,  7),
		"temperature"              : ePoint(1099,  0),
		"feeltemperature"          : ePoint(1167,  0),
		"minmaxtemperature"        : ePoint(1283,  0),
		"uvindexPixmap"            : ePoint(1440,  5),
		"uvindexLabel"             : ePoint(1433,  6),
		"uvindex"                  : ePoint(1473,  0),
		"sunpowerPixmap"           : ePoint(1530,  5),
		"sunpower"                 : ePoint(1563,  0)
	}

	def __init__(self, session):
		windSpeedUnit = int(settings.windSpeedUnit.value)
		self.position = int(settings.position.value)
		self.units["windspeedms"] = " " + _("km/h") if windSpeedUnit == 3 else (" " + _("mph") if windSpeedUnit == 4 else " " + _("m/s"))
		self.primarySkin = config.skin.primary_skin.value.split("/")[0]
		self.font = gFont("Regular", 26)
		self.initSkins()
		self.skin = self.skins[self.position - 1]
		InfoBarExtra.__init__(self, session)
		Screen.__init__(self, session)
		self.skinName = self.skinNames[self.position - 1]
		for item in xml.etree.ElementTree.ElementTree(xml.etree.ElementTree.fromstring(self.skin)).getroot().findall('./widget'):
			name = item.attrib["name"]
			if "rainMultiPixmap" in name or name == "precipitation":
				self.hasRainWidget = True
			if "MultiPixmap" in name or "pixmaps" in item.attrib:
				self[name] = MultiPixmap()
			elif "Pixmap" in name or "pixmap" in item.attrib:
				self[name] = Pixmap()
			elif "foregroundColors" in item.attrib:
				self[name] = MultiColorLabel()
			else:
				self[name] = Label("a")
				if name == "uvindexLabel":
					self[name].setText(_("UV"))
				if (windSpeedUnit == 1 and name == "windspeedms") or (windSpeedUnit != 1 and name == "beaufort"):
					self[name].hide()
				if name == "infoBarBackground":
					self.infoBarBackground = self[name]
					self.infoBarBackground.hide()
				elif name == "secondInfoBarBackground":
					self.secondInfoBarBackground = self[name]
					self.secondInfoBarBackground.hide()
				elif name == "notconfigured":
					self[name].setText(_("Please configure a location in plugin settings"))
					self[name].hide()
		if "zero" in self:
			self["zero"].setText("0")
		if "one" in self:
			self["one"].setText("1")
		if "two" in self:
			self["two"].setText("2")
		self.showWidgets(self.ALL)
		self.timer = eTimer()
		self.timer.callback.append(self.timerCB)

	def initSkins(self):
		self.skins = []
		self.skinNames = []
		for i in range(0, 3):
			secondInfoBarBackgroundColor = "#ff000000"
			if self.primarySkin == "PLi-FullNightHD":
				secondInfoBarBackgroundColor = "#2d101214"
			elif self.primarySkin == "PLi-FullHD" or self.primarySkin == "Pd1loi-HD-night":
				secondInfoBarBackgroundColor = "#54111112"
			imageDir = "%s/images" % PLUGIN_PATH
			windImageDir = imageDir + "/wind/"
			rainImageDir = imageDir + "/rain/"
			windPixmaps = ",".join([windImageDir + x + ".png" for x in self.windDirections])
			rainShadowPixmaps = ",".join([rainImageDir + "s%d.png" % x for x in range(0, 30)])
			rainPixmaps = ",".join([rainImageDir + "%d.png" % x for x in range(0, 30)])
			locationnameWidth = eLabel.calculateTextSize(self.font, settings.locationname.value, eSize(337, 45)).width()
			sunpowerWidth = eLabel.calculateTextSize(self.font, "119" + self.units["sunpower"], eSize(200, 45)).width()
			width = self.pos["sunpower"].x() - self.pos["regio"].x() - 337 + locationnameWidth + sunpowerWidth
			offsetX = int((1920 - width) / 2) - (337 - locationnameWidth) - 10  # 10?
			offsetY = 0
			if i == 1:
				screenName = "%sAbove" % PLUGIN_NAME
				position = "0,800"
				size = "1920,51"
				backgroundPixmap = "PLi-FullNightHD-background-above.png"
			elif i == 2:
				screenName = "%sTop" % PLUGIN_NAME
				position = "0,0"
				size = "1920,78"
				offsetY = 6
				backgroundPixmap = "PLi-FullNightHD-background-top.png"
			else:
				screenName = PLUGIN_NAME
				position = "392,845"
				if self.primarySkin == "Pd1loi-HD-night":
					size = "1408,51"
				else:
					size = "1248,51"
				offsetX = 0
				backgroundPixmap = "PLi-FullNightHD-background.png"
			startPosX = self.pos["rainWidgets"].x() + offsetX
			rainShadowWidgets = "\n\t\t".join(["<widget name=\"rainShadowMultiPixmap" + str(x) + "\" position=\"" + str(startPosX + 2 * x - 1) + "," + str(self.pos["rainWidgets"].y() + offsetY) + "\" size=\"1,31\" alphatest=\"blend\" pixmaps=\"%(rainShadowPixmaps)s\" />" % {"rainShadowPixmaps": rainShadowPixmaps} for x in range(0, 24)])
			rainWidgets = "\n\t\t".join(["<widget name=\"rainMultiPixmap" + str(x) + "\" position=\"" + str(startPosX + 2 * x) + "," + str(self.pos["rainWidgets"].y() + offsetY) + "\" size=\"3,31\" alphatest=\"blend\" pixmaps=\"%(rainPixmaps)s\" />" % {"rainPixmaps": rainPixmaps} for x in range(0, 24)])
			props = {
				"screenName"                   : screenName,
				"position"                     : position,
				"size"                         : size,
				"imageDir"                     : imageDir,
				"backgroundPixmap"             : backgroundPixmap,
				"windPixmaps"                  : windPixmaps,
				"secondInfoBarBackgroundColor" : secondInfoBarBackgroundColor,
				"rainShadowWidgets"            : rainShadowWidgets,
				"rainWidgets"                  : rainWidgets
			}
			for k, v in self.pos.items():
				props["%sXpos" % k] = v.x() + offsetX
				props["%sYpos" % k] = v.y() + offsetY
			self.skinNames.append(screenName)
			self.skins.append("""	<screen name="%(screenName)s" position="%(position)s" size="%(size)s" backgroundColor="#ff000000" zPosition="2" flags="wfNoBorder">
		<!-- SKINNERS: enable at most one of the following two lines -->
		<!--<widget name="infoBarBackground" position="0,0" size="%(size)s" zPosition="-1" backgroundColor="#ff000000" />-->
		<widget name="infoBarBackground" position="0,0" size="%(size)s" zPosition="-1" alphatest="off" pixmap="%(imageDir)s/%(backgroundPixmap)s" />

		<!-- SKINNERS: enable at most one of the following two lines -->
		<widget name="secondInfoBarBackground" position="0,0" size="%(size)s" zPosition="-1" backgroundColor="%(secondInfoBarBackgroundColor)s" />
		<!--<widget name="secondInfoBarBackground" position="0,0" size="%(size)s" zPosition="-1" alphatest="off" pixmap="" />-->

		<widget name="notconfigured" position="%(notconfiguredXpos)s,%(notconfiguredYpos)s" size="1096,45" borderWidth="1" valign="center" halign="center" foregroundColor="#00B6B6B6" backgroundColor="#18101214" font="Regular; 26" transparent="1" />
		<widget name="regio" position="%(regioXpos)s,%(regioYpos)s" size="337,45" borderWidth="1" valign="center" halign="right" foregroundColor="#00B6B6B6" backgroundColor="#18101214" font="Regular; 26" transparent="1" />
		<widget name="time" position="%(timeXpos)s,%(timeYpos)s" size="70,45" borderWidth="1" valign="center" halign="left" foregroundColor="#00B6B6B6" backgroundColor="#18101214" font="Regular; 26" transparent="1" />
		<widget name="sunrise" position="%(sunriseXpos)s,%(sunriseYpos)s" size="80,45" borderWidth="1" valign="center" halign="right" foregroundColor="#00B6B6B6" backgroundColor="#18101214" font="Regular; 26" transparent="1" />
		<widget name="sunrisesetPixmap" position="%(sunrisesetPixmapXpos)s,%(sunrisesetPixmapYpos)s" size="50,30" alphatest="blend" pixmap="%(imageDir)s/sunriseset.png" />
		<widget name="sunset" position="%(sunsetXpos)s,%(sunsetYpos)s" size="80,45" borderWidth="1" valign="center" halign="left" foregroundColor="#00B6B6B6" backgroundColor="#18101214" font="Regular; 26" transparent="1" />
		<widget name="humidityPixmap" position="%(humidityPixmapXpos)s,%(humidityPixmapYpos)s" size="30,30" alphatest="blend" pixmap="%(imageDir)s/droplet.png" />
		<widget name="humidity" position="%(humidityXpos)s,%(humidityYpos)s" size="80,45" borderWidth="1" valign="center" halign="left" foregroundColor="#00B6B6B6" backgroundColor="#18101214" font="Regular; 26" transparent="1" />
		%(rainShadowWidgets)s
		%(rainWidgets)s
		<widget name="zero" position="%(zeroXpos)s,%(zeroYpos)s" size="12,14" borderWidth="1" valign="top" halign="center" foregroundColor="#00B6B6B6" backgroundColor="#18101214" font="Regular; 11" transparent="1" />
		<widget name="one" position="%(oneXpos)s,%(oneYpos)s" size="12,14" borderWidth="1" valign="top" halign="center" foregroundColor="#00B6B6B6" backgroundColor="#18101214" font="Regular; 11" transparent="1" />
		<widget name="two" position="%(twoXpos)s,%(twoYpos)s" size="12,14" borderWidth="1" valign="top" halign="center" foregroundColor="#00B6B6B6" backgroundColor="#18101214" font="Regular; 11" transparent="1" />
		<widget name="winddirectionMultiPixmap" position="%(winddirectionMultiPixmapXpos)s,%(winddirectionMultiPixmapYpos)s" size="30,30" alphatest="blend" pixmaps="%(windPixmaps)s" />
		<widget name="beaufort" position="%(beaufortXpos)s,%(beaufortYpos)s" size="112,45" borderWidth="1" valign="center" halign="left" foregroundColor="#00B6B6B6" backgroundColor="#18101214" font="Regular; 26" transparent="1" />
		<widget name="windspeedms" position="%(windspeedmsXpos)s,%(windspeedmsYpos)s" size="200,45" borderWidth="1" valign="center" halign="left" foregroundColor="#00B6B6B6" backgroundColor="#18101214" font="Regular; 26" transparent="1" />
		<widget name="precipitationPixmap" position="%(precipitationPixmapXpos)s,%(precipitationPixmapYpos)s" size="30,30" alphatest="blend" pixmap="%(imageDir)s/rain.png" />
		<widget name="precipitation" position="%(precipitationXpos)s,%(precipitationYpos)s" size="200,45" borderWidth="1" valign="center" halign="left" foregroundColor="#00B6B6B6" backgroundColor="#18101214" font="Regular; 26" transparent="1" />
		<widget name="weatherPixmap" position="%(weatherPixmapXpos)s,%(weatherPixmapYpos)s" size="30,30" alphatest="blend" />
		<widget name="temperature" position="%(temperatureXpos)s,%(temperatureYpos)s" size="80,45" borderWidth="1" valign="center" halign="right" foregroundColor="#00B6B6B6" backgroundColor="#18101214" font="Regular; 26" transparent="1" />
		<widget name="feeltemperature" position="%(feeltemperatureXpos)s,%(feeltemperatureYpos)s" size="80,45" borderWidth="1" valign="center" halign="right" foregroundColors="#00B6B6B6,#29abe2,#ff5555" backgroundColor="#18101214" font="Regular; 26" transparent="1" />
		<widget name="minmaxtemperature" position="%(minmaxtemperatureXpos)s,%(minmaxtemperatureYpos)s" size="256,45" borderWidth="1" valign="center" halign="left" foregroundColor="#00B6B6B6" backgroundColor="#18101214" font="Regular; 26" transparent="1" />
		<widget name="uvindexPixmap" position="%(uvindexPixmapXpos)s,%(uvindexPixmapYpos)s" size="30,16" alphatest="blend" pixmap="%(imageDir)s/uv.png" />
		<widget name="uvindexLabel" position="%(uvindexLabelXpos)s,%(uvindexLabelYpos)s" size="45,45" borderWidth="1" valign="center" halign="center" foregroundColor="#00B6B6B6" backgroundColor="#18101214" font="Regular; 15" transparent="1" />
		<widget name="uvindex" position="%(uvindexXpos)s,%(uvindexYpos)s" size="200,45" borderWidth="1" valign="center" halign="left" foregroundColors="#B6B6B6,#3ea72d,#fff300,#f18b00,#ff5555,#b567a4" backgroundColor="#18101214" font="Regular; 26" transparent="1" />
		<widget name="sunpowerPixmap" position="%(sunpowerPixmapXpos)s,%(sunpowerPixmapYpos)s" size="30,30" alphatest="blend" pixmap="%(imageDir)s/sunpower.png" />
		<widget name="sunpower" position="%(sunpowerXpos)s,%(sunpowerYpos)s" size="200,45" borderWidth="1" valign="center" halign="left" foregroundColors="#B6B6B6,#3ea72d,#fff300,#f18b00,#ff5555,#b567a4" backgroundColor="#18101214" font="Regular; 26" transparent="1" />
	</screen>
""" % props)
		if not fileExists(tmpdir):
			os.mkdir(tmpdir)
		with open(tmpdir + "/skin.xml", "w") as f:
			f.write("\n".join(self.skins))

	def timerCB(self):
		self.checkIfStale()
		InfoBarExtra.timerCB(self)

	def downloadRainCB(self, result):
		try:
			with open(rainFile, "r") as f:
				txt = f.read()
		except IOError:
			return

		with self.lastUpdateLock:
			self.lastUpdate = datetime.datetime.now()

		lines = txt.replace("\r", "").split("\n")
		i = 0
		for line in lines:
			if i >= 24:
				break
			if line:
				pixmapNum = 0
				v = float(line.split("|")[0].replace(",", "."))
				if v:

					# TODO this might need work
					if v <= 125.0:
						pixmapNum = int(round(v / 15.625)) + 1
					elif v <= 136.0:
						pixmapNum = int(round((v - 125.0)/ 1.375)) + 9
					elif v <= 157.0:
						pixmapNum = int(round((v - 136.0)/ 2.625)) + 17
					else:
						pixmapNum = int(round((v - 157.0)/ 15.0)) + 25

				try:
					multiPixmap = self["rainMultiPixmap" + str(i)]
					multiPixmap.setPixmapNum(min(pixmapNum, len(multiPixmap.pixmaps) - 1))
					shadowMultiPixmap = self["rainShadowMultiPixmap" + str(i)]
					shadowMultiPixmap.setPixmapNum(min(pixmapNum, len(shadowMultiPixmap.pixmaps) - 1))
				except KeyError:
					pass  # some skinner removed the widget
			i += 1
		self.showWidgets(self.RAIN)

	def downloadIconCB(self, result):
		self["weatherPixmap"].instance.setPixmapFromFile(str(self.iconfilepath))
		self.showWidgets(self.WEATHER)

	def hideOrShowWidgets(self, how, what):
		if what & self.RAIN:
			hasRain = settings.hasRain.value
			for x in range(0, 24):
				if "rainMultiPixmap" + str(x) in self:
					if settings.showrain.value and settings.showrainforecast.value and how and hasRain:
						self["rainMultiPixmap" + str(x)].show()
					else:
						self["rainMultiPixmap" + str(x)].hide()
				if "rainShadowMultiPixmap" + str(x) in self:
					if settings.showrain.value and settings.showrainforecast.value and how and hasRain:
						self["rainShadowMultiPixmap" + str(x)].show()
					else:
						self["rainShadowMultiPixmap" + str(x)].hide()
			for x in ["zero", "one", "two"]:
				if x in self:
					if settings.showrain.value and settings.showrainforecast.value and how and hasRain:
						self[x].show()
					else:
						self[x].hide()
			for x in ["precipitation", "precipitationPixmap"]:
				if x in self:
					if settings.showrain.value and how and (not hasRain or not settings.showrainforecast.value):
						self[x].show()
					else:
						self[x].hide()
		if what & self.WEATHER:
			if "weatherPixmap" in self:
				if settings.showicon.value and how:
					self["weatherPixmap"].show()
				else:
					self["weatherPixmap"].hide()
		if what & self.REST:
			windSpeedUnit = int(settings.windSpeedUnit.value)
			position = int(settings.position.value)
			for x in self:
				if x[0] != '_' and "precipitation" not in x and "nfoBarBackground" not in x and "rainMultiPixmap" not in x and "rainShadowMultiPixmap" not in x and x != "weatherPixmap" and x != "zero" and x != "one" and x != "two" and x != "notconfigured":
					try:
						if x == 'sunrise' or x == 'sunset' or x == 'sunrisesetPixmap':
							attr = 'showsunriseset'
						elif x == 'humidity' or x == 'humidityPixmap':
							attr = 'showhumidity'
						elif x == 'windspeedms' or x == 'beaufort' or x == 'winddirectionMultiPixmap':
							attr = 'showwind'
						elif x == 'uvindexPixmap' or x == "uvindexLabel":
							attr = 'showuvindex'
						elif x == 'sunpowerPixmap':
							attr = 'showsunpower'
						else:
							attr = 'show' + x
						if hasattr(settings, attr) and getattr(settings, attr).value and how:
							if (windSpeedUnit == 1 and x == "windspeedms") or (windSpeedUnit != 1 and x == "beaufort"):
								continue
							if (x == "minmaxtemperature" or x.startswith("uvindex") or x.startswith("sunpower")) and position == 1:
								self[x].hide()
							else:
								self[x].show()
						else:
							self[x].hide()
					except (AttributeError, IndexError) as e:
						pass

	def hideWidgets(self, what):
		self.hideOrShowWidgets(False, what)

	def showWidgets(self, what):
		self.hideOrShowWidgets(True, what)

	def errback(self, failure):
		print("[%s] error: %s" % (TAG, str(failure)))

	def updateUI(self, result):
		try:
			with open(jsonFile, "r") as f:
				j = json.loads(f.read())
		except (IOError, ValueError) as e:
			return

		with self.lastUpdateLock:
			self.lastUpdate = datetime.datetime.now()

		h = j['days'][0]['hours']
		d = h[0]

		self.beaufort        = d['beaufort']
		self.windspeedms     = d['windspeedms']
		self.temperature     = d['temperature']
		self.feeltemperature = d['feeltemperature']

		windSpeedUnit   = int(settings.windSpeedUnit.value)
		temperatureUnit = int(settings.temperatureUnit.value)
		x = {}
		x['regio']             = settings.displayas.value if settings.displayas.value else settings.locationname.value
		x['temperature']       = round(d['temperature'] * 1.8 + 32, 1) if temperatureUnit == 2 else d['temperature']
		x['feeltemperature']   = round(d['feeltemperature'] * 1.8 + 32, 1) if temperatureUnit == 2 else d['feeltemperature']
		mintemperature         = round(j['days'][0]['mintemperature'] * 1.8 + 32, 1) if temperatureUnit == 2 else j['days'][0]['mintemperature']
		maxtemperature         = round(j['days'][0]['maxtemperature'] * 1.8 + 32, 1) if temperatureUnit == 2 else j['days'][0]['maxtemperature']
		x['minmaxtemperature'] = "%s%s - %s%s" % (mintemperature, self.units["mintemperature"], maxtemperature, self.units["maxtemperature"])
		x['beaufort']          = d['beaufort']
		x['windspeedms']       = int(round(d['windspeedms'])) if windSpeedUnit == 2 else (int(round(d['windspeedms'] * 3.6)) if windSpeedUnit == 3 else int(round(d['windspeedms'] * 2.236936)))
		x['humidity']          = d['humidity']
		x['precipitation']     = d['precipitation']
		x['uvindex']           = j['days'][0]['uvindex']
		x['sunpower']          = d['sunpower']

		if "weatherPixmap" in self and "iconcode" in d:
			iconFileExists = False
			iconurl = "https://www.buienradar.nl/resources/images/icons/weather/30x30/" + d["iconcode"] + ".png"
			filename = iconurl.split("/")[-1]
			self.iconfilepath = PLUGIN_PATH + "/images/icons/" + filename
			if fileExists(self.iconfilepath):
				iconFileExists = True
			else:
				self.iconfilepath = tmpdir + "/" + filename
				if fileExists(self.iconfilepath):
					iconFileExists = True
			if not iconFileExists:
				print("[%s] downloading %s to %s" % (TAG, str(iconurl), self.iconfilepath))
				download(str(iconurl), self.iconfilepath).start().addCallback(self.downloadIconCB).addErrback(self.errback)
			else:
				try:
					self["weatherPixmap"].instance.setPixmapFromFile(str(self.iconfilepath))
					self.showWidgets(self.WEATHER)
				except Exception as e:
					self["weatherPixmap"].hide()
					print("[%s] Exception: %s" % (TAG, e))
		if "winddirectionMultiPixmap" in self and "winddirection" in d:
			try:
				self["winddirectionMultiPixmap"].setPixmapNum(self.windDirections.index(d["winddirection"]))
			except IndexError:
				print("[%s] IndexError: %s" % (TAG, d["winddirection"]))
		try:
			x["sunrise"] = j['days'][0]['sunrise'].split('T')[1][:5]
		except KeyError:
			pass
		try:
			x["sunset"] = j['days'][0]['sunset'].split('T')[1][:5]
		except KeyError:
			pass
		try:
			dt = datetime.datetime.strptime(j['timestamp'], '%Y-%m-%dT%H:%M:%S')
			x["time"] = str(dt + datetime.timedelta(hours=j['timeOffset']))[11:-3]
		except KeyError:
			pass
		for y in x:
			if y in self:
				try:
					unit = self.units[y]
				except KeyError:
					unit = ""
				cur_val = str(x[y])
				if y in ["humidity", "rainFallLastHour", "sunpower"]:
					cur_val = str(int(round(float(cur_val))))
				cur_val += unit
				self[y].setText(cur_val)
				if y == "feeltemperature" and "temperature" in x:
					if float(x[y]) > float(x["temperature"]):
						self[y].setForegroundColorNum(2)
					elif float(x[y]) < float(x["temperature"]):
						self[y].setForegroundColorNum(1)
					else:
						self[y].setForegroundColorNum(0)
				if y == "uvindex":
					uv = x[y]
					if uv == 0:
						self[y].setForegroundColorNum(0)
					elif uv <= 2:
						self[y].setForegroundColorNum(1)
					elif uv <= 5:
						self[y].setForegroundColorNum(2)
					elif uv <= 7:
						self[y].setForegroundColorNum(3)
					elif uv <= 10:
						self[y].setForegroundColorNum(4)
					else:
						self[y].setForegroundColorNum(5)
		if self.hasRainWidget and not settings.hasRain.value:
			self.showWidgets(self.RAIN)
		self.showWidgets(self.REST)

	def _onShowInfoBar(self, parent):
		if isinstance(parent, InfoBarEPG):
			self.show()
			self.onShowHideInfoBar(True)

	def _onHideInfoBar(self):
		if self.shown:
			self.hide()
			self.onShowHideInfoBar(False)

	def _onShowSecondInfoBar(self):
		if self.position != 1 and self.shown:
			self.hide()
		else:
			self.onShowHideSecondInfoBar(True)

	def _onHideSecondInfoBar(self):
		if self.position != 1 and not self.shown:
			self.show()
		else:
			self.onShowHideSecondInfoBar(False)

	def checkIfStale(self):
		locationid = settings.locationid.value
		if locationid == 0:
			self.hideWidgets(self.ALL)
			self["notconfigured"].show()
			return
		now = datetime.datetime.now()
		with self.lastUpdateLock:
			lastUpdateDiff = now - self.lastUpdate
		if lastUpdateDiff.days or lastUpdateDiff.seconds >= self.updateInterval * 60:
			self.hideWidgets(self.ALL)
			url = jsonUrl % locationid
			print("[%s] downloading %s to %s" % (TAG, url, jsonFile))
			download(url, jsonFile).start().addCallback(self.updateUI)
			if self.hasRainWidget and settings.hasRain.value:
				lat = float(settings.locationlat.value)
				lon = float(settings.locationlon.value)
				url = rainForecastUrl % (lat, lon)
				print("[%s] downloading %s to %s" % (TAG, url, rainFile))
				download(url, rainFile).start().addCallback(self.downloadRainCB)

	def onShowHideInfoBar(self, shown):
		if not settings.enabled.value:
			return
		print("[%s] onShowHideInfoBar(%s)" % (TAG, str(shown)))
		if (shown):
			self.checkIfStale()
			if self.infoBarBackground:
				self.infoBarBackground.show()
			if self.secondInfoBarBackground:
				self.secondInfoBarBackground.hide()
			self.timer.start(60 * 1000)
		else:
			self.timer.stop()
		InfoBarExtra.onShowHideInfoBar(self, shown)

	def onShowHideSecondInfoBar(self, shown):
		if not settings.enabled.value:
			return
		print("[%s] onShowHideSecondInfoBar(%s)" % (TAG, str(shown)))
		if (shown):
			if self.infoBarBackground:
				self.infoBarBackground.hide()
			if self.secondInfoBarBackground:
				self.secondInfoBarBackground.show()
		InfoBarExtra.onShowHideSecondInfoBar(self, shown)


class LocationList(MenuList):

	def __init__(self, list, selection=0, enableWrapAround=False):
		MenuList.__init__(self, list, enableWrapAround, eListboxPythonMultiContent)
		self.l.setFont(0, gFont("Regular", 26))
		self.l.setItemHeight(45)
		self.selection = selection

	@staticmethod
	def entry(locationid, locationname, province, country, lat, lon):
		l = [locationid]
		lonStart = 1010
		lonWidth = 90
		latStart = 910
		latWidth = 90
		countryStart = 670
		countryWidth = 270
		provinceStart = 380
		provinceWidth = 270
		locationnameStart = 10
		locationnameWidth = 360
		itemHeight = 45
		l.append((eListboxPythonMultiContent.TYPE_TEXT, lonStart,          0, lonWidth,          itemHeight, 0, RT_HALIGN_RIGHT | RT_VALIGN_CENTER, lon))
		l.append((eListboxPythonMultiContent.TYPE_TEXT, latStart,          0, latWidth,          itemHeight, 0, RT_HALIGN_RIGHT | RT_VALIGN_CENTER, lat))
		l.append((eListboxPythonMultiContent.TYPE_TEXT, countryStart,      0, countryWidth,      itemHeight, 0, RT_HALIGN_LEFT  | RT_VALIGN_CENTER, country))
		l.append((eListboxPythonMultiContent.TYPE_TEXT, provinceStart,     0, provinceWidth,     itemHeight, 0, RT_HALIGN_LEFT  | RT_VALIGN_CENTER, province))
		l.append((eListboxPythonMultiContent.TYPE_TEXT, locationnameStart, 0, locationnameWidth, itemHeight, 0, RT_HALIGN_LEFT  | RT_VALIGN_CENTER, locationname))
		return l

	def applySkin(self, desktop, parent):
		attribs = []
		if self.skinAttributes is not None:
			for (attrib, value) in self.skinAttributes:
				if attrib == "font":
					self.font = parseFont(value, ((1, 1), (1, 1)))
					self.l.setFont(0, self.font)
				elif attrib == "itemHeight":
					self.l.setItemHeight(int(value))
				else:
					attribs.append((attrib, value))
			self.skinAttributes = attribs
		return MenuList.applySkin(self, desktop, parent)

	def postWidgetCreate(self, instance):
		MenuList.postWidgetCreate(self, instance)
		self.moveToIndex(self.selection)


class SelectLocationScreen(Screen):

	def __init__(self, session):
		primarySkin = config.skin.primary_skin.value.split("/")[0]
		if primarySkin == "PLi-FullNightHD" or primarySkin == "PLi-FullHD" or primarySkin == "Pd1loi-HD-night":
			self.skin = """
				<screen name=\"""" + PLUGIN_NAME + """SelectLocation" position="fill" flags="wfNoBorder">
					<panel name="PigTemplate"/>
					<panel name="ButtonRed"/>
					<panel name="ButtonGreen"/>
					<panel name="KeyOkTemplate"/>
					<widget name="city" position="790,103" size="200,45" font="Regular; 28" />
					<widget name="province" position="1160,103" size="200,45" font="Regular; 28" />
					<widget name="country" position="1451,103" size="200,45" font="Regular; 28" />
					<widget name="lat" position="1740,103" size="80,45" font="Regular; 28" />
					<widget name="lon" position="1834,103" size="80,45" font="Regular; 28" />
					<widget name="locationList" position="780,153" size="1109,855" font="Regular; 26" itemHeight="45" scrollbarMode="showOnDemand" />
				</screen>"""
		else:
			self.skin = """
				<screen name=\"""" + PLUGIN_NAME + """SelectLocation" position="center,center" size="1150,715">
					<widget name="city" position="20,9" size="200,45" font="Regular; 28" />
					<widget name="province" position="390,9" size="200,45" font="Regular; 28" />
					<widget name="country" position="681,9" size="200,45" font="Regular; 28" />
					<widget name="lat" position="971,9" size="80,45" font="Regular; 28" />
					<widget name="lon" position="1064,9" size="80,45" font="Regular; 28" />
					<widget name="locationList" position="10,55" size="e-10,e-130" font="Regular; 26" itemHeight="45" scrollbarMode="showOnDemand" />
					<ePixmap pixmap="skin_default/buttons/key_ok.png" position="10,e-42" zPosition="0" size="35,25" transparent="1" alphatest="on" />
					<ePixmap pixmap="skin_default/buttons/red.png" position="55,e-50" zPosition="0" size="140,40" transparent="1" alphatest="on" />
					<ePixmap pixmap="skin_default/buttons/green.png" position="195,e-50" zPosition="0" size="140,40" transparent="1" alphatest="on" />
					<widget name="key_red" position="55,e-50" zPosition="1" size="140,40" font="Regular; 20" valign="center" halign="center" backgroundColor="#9f1313" transparent="1" />
					<widget name="key_green" position="195,e-50" zPosition="1" size="140,40" font="Regular; 20" valign="center" halign="center" backgroundColor="#1f771f" transparent="1" />
				</screen>"""
		self.session = session
		Screen.__init__(self, session)
		self.skinName = PLUGIN_NAME + "SelectLocation"
		self.setTitle(_("Select location"))

		self["actions"] = ActionMap(["SetupActions", "ColorActions"],
		{
			"ok": self.keyOk,
			"green": self.keyOk,
			"cancel": self.keyCancel,
			"red": self.keyCancel,
		}, -2)

		with open(tmpdir + '/locations.json', "r") as f:
			try:
				self.json = json.loads(f.read())
			except ValueError:
				self.session.open(MessageBox, _("Could not parse location data."), MessageBox.TYPE_ERROR)
				self.close()
				return
		if fileExists(tmpdir + '/locations.json'):
			os.unlink(tmpdir + '/locations.json')

		self.locationList = []
		for x in self.json:
			try:
				name = str(x["name"])
			except KeyError:
				name = ''
			try:
				province = str(x["foad"]["name"])
			except KeyError:
				province = ''
			try:
				provincecode = " (" + str(x["foad"]["code"]) + ")"
			except KeyError:
				provincecode = ''
			try:
				country = str(x["country"])
			except KeyError:
				country = ''
			try:
				countrycode = " (" + str(x["countrycode"]) + ")"
			except KeyError:
				countrycode = ''
			try:
				lat = "{:.2f}".format(x["location"]["lat"])
			except KeyError:
				lat = ''
			try:
				lon = "{:.2f}".format(x["location"]["lon"])
			except KeyError:
				lon = ''
			self.locationList.append(LocationList.entry(x["id"], name, province + provincecode, country + countrycode, lat, lon))
		self["city"] = Label(_("Location"))
		self["province"] = Label(_("State/province"))
		self["country"] = Label(_("Country"))
		self["lat"] = Label(_("Lat"))
		self["lon"] = Label(_("Lon"))
		self["locationList"] = LocationList(list=self.locationList)
		self["key_red"] = Button(_("Cancel"))
		if len(self.locationList) > 0:
			self["key_green"] = Button(_("Select"))

	def keyOk(self):
		current = self["locationList"].getCurrent()
		if current is None:
			return
		locationid = current[0]
		if settings.locationid.value != locationid:
			country = current[1][7]
			hasRain = country == "Nederland (NL)" or country == "België (BE)"
			locationname = current[3][7]
			for x in self.json:
				if x['id'] == locationid:
					locationlat = str(x["location"]["lat"])
					locationlon = str(x["location"]["lon"])
					break
			self.close(locationid, country, hasRain, locationname, locationlat, locationlon)
		else:
			self.close()

	def keyCancel(self):
		self.close()


class SetupScreen(Screen, ConfigListScreen):

	def __init__(self, session):
		primarySkin = config.skin.primary_skin.value.split("/")[0]
		if primarySkin == "PLi-FullNightHD" or primarySkin == "PLi-FullHD" or primarySkin == "Pd1loi-HD-night":
			self.skin = """
				<screen name=\"""" + PLUGIN_NAME + """Setup" position="fill" flags="wfNoBorder">
					<panel name="PigTemplate"/>
					<panel name="VKeyIconPanel"/>
					<widget name="description" position="30,570" size="720,300" itemHeight="38" font="Regular;30" valign="top"/>
					<panel name="ButtonRed"/>
					<panel name="ButtonGreen"/>
					<panel name="KeyOkTemplate"/>
					<widget name="config" position="780,120" size="1109,855" font="Regular; 28" itemHeight="45" scrollbarMode="showOnDemand" />
				</screen>"""
		else:
			self.skin = """
				<screen name=\"""" + PLUGIN_NAME + """Setup" position="center,center" size="1110,715">
					<widget name="description" position="21,551" size="1059,114" itemHeight="38" font="Regular;30" valign="top" />
					<widget name="config" position="5,5" size="1100,540" font="Regular; 28" itemHeight="45" scrollbarMode="showOnDemand" />
					<ePixmap pixmap="skin_default/buttons/key_ok.png" position="10,e-42" zPosition="0" size="35,25" transparent="1" alphatest="on" />
					<ePixmap pixmap="skin_default/buttons/red.png" position="55,e-50" zPosition="0" size="140,40" transparent="1" alphatest="on" />
					<ePixmap pixmap="skin_default/buttons/green.png" position="195,e-50" zPosition="0" size="140,40" transparent="1" alphatest="on" />
					<widget name="key_red" position="55,e-50" zPosition="1" size="140,40" font="Regular; 20" valign="center" halign="center" backgroundColor="#9f1313" transparent="1" />
					<widget name="key_green" position="195,e-50" zPosition="1" size="140,40" font="Regular; 20" valign="center" halign="center" backgroundColor="#1f771f" transparent="1" />
				</screen>"""
		self.session = session
		self.locationid = settings.locationid.value
		self.hasRain = settings.hasRain.value
		self.locationname = settings.locationname.value
		self.locationlat = settings.locationlat.value
		self.locationlon = settings.locationlon.value
		Screen.__init__(self, session)
		ConfigListScreen.__init__(self, [], session=session) #, on_change=self.changed)
		self.skinName = PLUGIN_NAME + "Setup"
		self.setTitle(_("InfoBarWeather %(version)s setup" % {"version": VERSION}))
		self.onLayoutFinish.append(self.initConfiglist)
		self.onClose.append(self.deinitConfig)
		locationname = settings.locationname.value
		if locationname is not None and locationname != '':
			settings.locationname2.setCurrentText(locationname)
		self["setupActions"] = ActionMap(["SetupActions", "ColorActions"], {
			"red": self.keyCancel,
			"green": self.keySave,
			"cancel": self.keyCancel,
			"save": self.keySave,
			"ok": self.keyOk,
		}, -2)
		self["key_red"] = Button(_("Cancel"))
		self["key_green"] = Button(_("Save"))
		self["description"] = Label("")
		self["VirtualKB"].setEnabled(False)
		self["VKeyIcon"] = Boolean(False)
		self["HelpWindow"] = Pixmap()
		self["HelpWindow"].hide()

	def initConfiglist(self):
		settings.enabled.addNotifier(self.buildConfiglist, initial_call=False)
		settings.position.addNotifier(self.buildConfiglist, initial_call=False)
		settings.showrain.addNotifier(self.buildConfiglist, initial_call=False)
		self.buildConfiglist()

	def deinitConfig(self):
		settings.showrain.removeNotifier(self.buildConfiglist)
		settings.position.removeNotifier(self.buildConfiglist)
		settings.enabled.removeNotifier(self.buildConfiglist)

	def buildConfiglist(self, configElement=None):
		cfgList = [getConfigListEntry(_('Enabled'), settings.enabled)]
		if settings.enabled.value:
			cfgList.extend([
				getConfigListEntry(_('Location'), settings.locationname2, _("Press OK to open location search.")),
				getConfigListEntry(_('Display location as'), settings.displayas),
				getConfigListEntry(_('Position'), settings.position),
				getConfigListEntry(_('Wind speed unit'), settings.windSpeedUnit, _("Display wind speed as BFT, m/s, km/h or mph.")),
				getConfigListEntry(_('Temperature unit'), settings.temperatureUnit, _("Display temperature as °C or °F.")),
				getConfigListEntry(_('Show location'), settings.showregio),
				getConfigListEntry(_('Show last update time'), settings.showtime, _("Show last update time by weather service.")),
				getConfigListEntry(_('Show sunrise/sunset'), settings.showsunriseset),
				getConfigListEntry(_('Show humidity'), settings.showhumidity),
				getConfigListEntry(_('Show rain'), settings.showrain)])
			if self.hasRain and settings.showrain.value:
				cfgList.append(getConfigListEntry(_('Show rain forecast'), settings.showrainforecast, _("Show two hour rain forecast instead of rain probability (only available for The Netherlands and Belgium).")))
			cfgList.extend([
				getConfigListEntry(_('Show wind'), settings.showwind),
				getConfigListEntry(_('Show icon'), settings.showicon),
				getConfigListEntry(_('Show temperature'), settings.showtemperature),
				getConfigListEntry(_('Show feel temperature'), settings.showfeeltemperature)])
			if int(settings.position.value) != 1:
				cfgList.extend([
					getConfigListEntry(_('Show min/max temperature'), settings.showminmaxtemperature),
					getConfigListEntry(_('Show UV index'), settings.showuvindex),
					getConfigListEntry(_('Show sun power'), settings.showsunpower)])
		self["config"].list = cfgList
		self["config"].l.setList(cfgList)

	def keyCancel(self):
		ConfigListScreen.keyCancel(self)

	def keySave(self):
		settings.locationid.value = self.locationid
		settings.locationid.save()
		settings.hasRain.value = self.hasRain
		settings.hasRain.save()
		settings.locationname.value = self.locationname
		settings.locationname.save()
		settings.locationlat.value = self.locationlat
		settings.locationlat.save()
		settings.locationlon.value = self.locationlon
		settings.locationlon.save()
		ConfigListScreen.keySave(self)
		start(SETTINGSCHANGE, reason=1)
		if settings.enabled.value:
			start(SETTINGSCHANGE, reason=0)

	def keyOk(self):
		sel = self["config"].getCurrent()[1]
		if sel and sel == settings.locationname2:
			self.session.openWithCallback(self.downloadLocations, VirtualKeyBoard, title=(_("Enter (part of) location to search for (e.g. \"Amsterdam\" or \"Ams\"):")))

	def downloadLocations(self, searchterm):
		if searchterm is None or searchterm == '':
			return
		self["config"].hide()
		self["description"].hide()
		url = 'https://location.buienradar.nl/1.1/location/search?query=' + quote(searchterm)
		print("[%s] downloading %s to %s" % (TAG, url, tmpdir + '/locations.json'))
		download(url, tmpdir + '/locations.json').start().addCallback(self.downloadLocationsSuccessCB).addErrback(self.downloadLocationsFailureCB)

	def downloadLocationsSuccessCB(self, result):
		self.session.openWithCallback(self.selectLocationScreenCB, SelectLocationScreen)
		self["config"].show()
		self["description"].show()
		return result

	def downloadLocationsFailureCB(self, failure):
		self.session.open(MessageBox, _("Could not download location data."), MessageBox.TYPE_ERROR)
		self["config"].show()
		self["description"].show()
		return failure

	def selectLocationScreenCB(self, locationid=None, country=None, hasRain=None, locationname=None, locationlat=None, locationlon=None):
		if locationid is not None:
			self.locationid = locationid
			self.country = country
			prevHasRain = self.hasRain
			self.hasRain = hasRain
			self.locationname = locationname
			self.locationlat = locationlat
			self.locationlon = locationlon
			settings.displayas.value = locationname
			settings.locationname2.setCurrentText(locationname)
			if hasRain != prevHasRain:
				self.buildConfiglist()


def setup(session, **kwargs):
	session.open(SetupScreen)

started = False
baseInfoBarShowHide__init__ = None
InfoBarWeatherDialog = None
InfoBarWeatherDialog_onShowInfoBar = None

def newInfoBarShowHide__init__(self):
	global InfoBarWeatherDialog, InfoBarWeatherDialog_onShowInfoBar
	if baseInfoBarShowHide__init__ is not None:
		baseInfoBarShowHide__init__(self)
	if InfoBarWeatherDialog is not None:
		return
	InfoBarWeatherDialog = self.session.instantiateDialog(InfoBarWeather)
	InfoBarWeatherDialog_onShowInfoBar = boundFunction(InfoBarWeatherDialog._onShowInfoBar, self)
	self.onShow.append(InfoBarWeatherDialog_onShowInfoBar)
	self.onHide.append(InfoBarWeatherDialog._onHideInfoBar)
	if hasattr(self, "actualSecondInfoBarScreen") and self.actualSecondInfoBarScreen:
		self.actualSecondInfoBarScreen.onShow.append(InfoBarWeatherDialog._onShowSecondInfoBar)
		self.actualSecondInfoBarScreen.onHide.append(InfoBarWeatherDialog._onHideSecondInfoBar)

def newInfoBarShowHide__del__(self):
	global InfoBarWeatherDialog, InfoBarWeatherDialog_onShowInfoBar
	if hasattr(self, "actualSecondInfoBarScreen") and self.actualSecondInfoBarScreen:
		try:
			self.actualSecondInfoBarScreen.onHide.remove(InfoBarWeatherDialog._onHideSecondInfoBar)
		except ValueError:
			pass
		try:
			self.actualSecondInfoBarScreen.onShow.remove(InfoBarWeatherDialog._onShowSecondInfoBar)
		except ValueError:
			pass
	try:
		self.onHide.remove(InfoBarWeatherDialog._onHideInfoBar)
	except ValueError:
		pass
	try:
		self.onShow.remove(InfoBarWeatherDialog_onShowInfoBar)
	except ValueError:
		pass
	InfoBarWeatherDialog.close()
	InfoBarWeatherDialog = None

AUTOSTART = "autostart"
SESSIONSTART = "sessionstart"
SETTINGSCHANGE = "settingschange"

def start(why, **kwargs):
	global started, baseInfoBarShowHide__init__
	if "reason" in kwargs:
		if kwargs["reason"] == 0 and (why == SETTINGSCHANGE or settings.enabled.value):
			print("[%s] %s(reason=0)" % (TAG, why))
			if not started:
				# we've just been installed or enabled
				started = True
				if InfoBar.instance is not None:
					print("[%s] InfoBar is already instantiated, modifying existing InfoBar instance" % TAG)
					newInfoBarShowHide__init__(InfoBar.instance)
				else:
					print("[%s] InfoBar is not yet instantiated, monkey-patching InfoBarShowHide" % TAG)
					baseInfoBarShowHide__init__ = InfoBarShowHide.__init__
					InfoBarShowHide.__init__ = newInfoBarShowHide__init__
		elif kwargs["reason"] == 1 and (why == SETTINGSCHANGE or not settings.enabled.value):
			print("[%s] %s(reason=1)" % (TAG, why))
			if started:
				# we've just been uninstalled or disabled
				print("[%s] removing from InfoBar" % TAG)
				started = False
				if baseInfoBarShowHide__init__ is not None:
					InfoBarShowHide.__init__ = baseInfoBarShowHide__init__
					baseInfoBarShowHide__init__ = None
				newInfoBarShowHide__del__(InfoBar.instance)

def autostart(**kwargs):
	start(AUTOSTART, **kwargs)

def sessionstart(**kwargs):
	start(SESSIONSTART, **kwargs)

def Plugins(**kwargs):
	return [PluginDescriptor(name=PLUGIN_NAME, description=_("Show current weather in infobar"), where=PluginDescriptor.WHERE_AUTOSTART, fnc=autostart),
			PluginDescriptor(name=PLUGIN_NAME, description=_("Show current weather in infobar"), where=PluginDescriptor.WHERE_SESSIONSTART, fnc=sessionstart),
			PluginDescriptor(name=PLUGIN_NAME, description=_("Show current weather in infobar"), where=PluginDescriptor.WHERE_PLUGINMENU, fnc=setup, icon="plugin.png")]
