# -*- coding: UTF-8 -*-

# InfoBarWeather by scriptmelvin
# https://github.com/scriptmelvin/enigma2-plugin-extensions-infobarweather
# License: GPL-2.0

VERSION = '0.10'

from . import _, _N, PLUGIN_PATH, PLUGIN_NAME
from Components.ActionMap import ActionMap
from Components.Button import Button
from Components.config import config, ConfigBoolean, ConfigInteger, ConfigSelection, ConfigSubsection, ConfigText, ConfigYesNo, getConfigListEntry
from Components.ConfigList import ConfigListScreen
from Components.Label import Label, MultiColorLabel
from Components.MenuList import MenuList
from Components.Pixmap import MultiPixmap, Pixmap
from enigma import eListboxPythonMultiContent, eTimer, getDesktop, gFont, RT_HALIGN_LEFT, RT_VALIGN_CENTER
from Plugins.Plugin import PluginDescriptor
from Screens.InfoBar import InfoBar
from Screens.InfoBarGenerics import InfoBarEPG, InfoBarShowHide
from Screens.MessageBox import MessageBox
from Screens.Screen import Screen
from Screens.VirtualKeyBoard import VirtualKeyBoard
from skin import parseFont
from Tools.BoundFunction import boundFunction
from Tools.Directories import fileExists
from Tools.Downloader import downloadWithProgress

import datetime
import json
import os
import sys
import threading
import time
import xml

try:
	from urllib import quote
except ImportError:
	from urllib.parse import quote

setattr(config.plugins, PLUGIN_NAME, ConfigSubsection())
settings = getattr(config.plugins, PLUGIN_NAME)
settings.enabled = ConfigYesNo(True)
settings.locationid = ConfigInteger(0)
settings.locationlat = ConfigText()
settings.locationlon = ConfigText()
settings.locationname = ConfigText()
settings.locationname2 = ConfigSelection([_("Press OK")])
settings.windSpeedUnit = ConfigSelection(choices=[("1", _("BFT")), ("2", _("m/s")), ("3", _("km/h"))], default="1")
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
settings.hasRain = ConfigBoolean()


jsonUrl = "https://forecast.buienradar.nl/2.0/forecast/%d"
rainForecastUrl = "https://gps.buienradar.nl/getrr.php?lat=%g&lon=%g"
tmpdir = "/tmp/%s" % PLUGIN_NAME
jsonFile = "%s/weather.json" % tmpdir
rainFile = "%s/rainForecast.txt" % tmpdir

TAG = PLUGIN_NAME
infoBarWeatherInstance = None

desktopWidth = getDesktop(0).size().width()

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
	units = {"airpressure": " hPa", "feeltemperature": "°", "groundtemperature": "°", "humidity": "%", "precipitation": "%", "rainFallLast24Hour": " mm", "rainFallLastHour": " mm", "sunpower": " W/m²", "temperature": "°", "visibility": " m", "winddirectiondegrees": "°", "windgusts": " m/s", "windspeedms": " m/s", "beaufort": " BFT"}
	infoBarBackground = None
	secondInfoBarBackground = None
	lastUpdate = datetime.datetime.min
	updateInterval = 10 # minutes
	lastUpdateLock = threading.Lock()

	def __init__(self, session):
		windSpeedUnit = int(settings.windSpeedUnit.value)
		self.units["windspeedms"] = " " + _("km/h") if windSpeedUnit == 3 else " " + _("m/s")
		secondInfoBarBackgroundColor = "#ff000000"
		primarySkin = config.skin.primary_skin.value.split("/")[0]
		if primarySkin == "PLi-FullNightHD":
			secondInfoBarBackgroundColor = "#2d101214"
		elif primarySkin == "PLi-FullHD" or primarySkin == "Pd1loi-HD-night":
			secondInfoBarBackgroundColor = "#54111112"
		imageDir = "%s/images" % PLUGIN_PATH
		windImageDir = imageDir + "/wind/"
		rainImageDir = imageDir + "/rain/"
		windPixmaps = ",".join([windImageDir + x + ".png" for x in self.windDirections])
		rainPixmaps = ",".join([rainImageDir + "%d.png" % x for x in range(0, 30)])
		startPos = 826
		rainWidgets = "\n\t\t\t\t".join(["<widget name=\"rainMultiPixmap" + str(x) + "\" position=\"" + str(startPos + 2 * x) + ",2\" size=\"2,29\" alphatest=\"blend\" pixmaps=\"%(rainPixmaps)s\" />" % {"rainPixmaps": rainPixmaps} for x in range(0, 24)])
		self.skin = """
			<screen name="%(screen_name)s" position="384,845" size="1416,51" backgroundColor="#ff000000" zPosition="2" flags="wfNoBorder">
				<!-- SKINNERS: enable at most one of the following two lines -->
				<!--<widget name="infoBarBackground" position="0,0" size="1536,51" zPosition="-1" backgroundColor="#ff000000" />-->
				<widget name="infoBarBackground" position="0,0" size="1536,51" zPosition="-1" alphatest="off" pixmap="%(imageDir)s/PLi-FullNightHD-background.png" />

				<!-- SKINNERS: enable at most one of the following two lines -->
				<widget name="secondInfoBarBackground" position="0,0" size="1536,51" zPosition="-1" backgroundColor="%(secondInfoBarBackgroundColor)s" />
				<!--<widget name="secondInfoBarBackground" position="0,0" size="1536,51" zPosition="-1" alphatest="off" pixmap="" />-->

				<widget name="notconfigured" position="18,0" size="1096,45" valign="center" halign="center" foregroundColor="#00B6B6B6" backgroundColor="#18101214" font="Regular; 26" transparent="1" />
				<widget name="regio" position="18,0" size="337,45" valign="center" halign="right" foregroundColor="#00B6B6B6" backgroundColor="#18101214" font="Regular; 26" transparent="1" />
				<widget name="time" position="360,0" size="70,45" valign="center" halign="left" foregroundColor="#00B6B6B6" backgroundColor="#18101214" font="Regular; 26" transparent="1" />
				<widget name="sunrise" position="450,0" size="80,45" valign="center" halign="right" foregroundColor="#00B6B6B6" backgroundColor="#18101214" font="Regular; 26" transparent="1" />
				<widget name="sunrisesetPixmap" position="538,7" size="50,30" alphatest="blend" pixmap="%(imageDir)s/sunriseset.png" />
				<widget name="sunset" position="595,0" size="80,45" valign="center" halign="left" foregroundColor="#00B6B6B6" backgroundColor="#18101214" font="Regular; 26" transparent="1" />
				<widget name="humidityPixmap" position="698,7" size="30,30" alphatest="blend" pixmap="%(imageDir)s/droplet.png" />
				<widget name="humidity" position="726,0" size="80,45" valign="center" halign="left" foregroundColor="#00B6B6B6" backgroundColor="#18101214" font="Regular; 26" transparent="1" />
				<widget name="winddirectionMultiPixmap" position="915,7" size="30,30" alphatest="blend" pixmaps="%(windPixmaps)s" />
				<widget name="beaufort" position="948,0" size="112,45" valign="center" halign="left" foregroundColor="#00B6B6B6" backgroundColor="#18101214" font="Regular; 26" transparent="1" />
				<widget name="windspeedms" position="948,0" size="200,45" valign="center" halign="left" foregroundColor="#00B6B6B6" backgroundColor="#18101214" font="Regular; 26" transparent="1" />
				%(rainWidgets)s
				<widget name="zero" position="820,30" size="12,14" valign="top" halign="center" foregroundColor="#00B6B6B6" backgroundColor="#18101214" font="Regular; 11" transparent="1" />
				<widget name="one" position="844,30" size="12,14" valign="top" halign="center" foregroundColor="#00B6B6B6" backgroundColor="#18101214" font="Regular; 11" transparent="1" />
				<widget name="two" position="868,30" size="12,14" valign="top" halign="center" foregroundColor="#00B6B6B6" backgroundColor="#18101214" font="Regular; 11" transparent="1" />
				<widget name="precipitationPixmap" position="806,7" size="30,30" alphatest="blend" pixmap="%(imageDir)s/rain.png" />
				<widget name="precipitation" position="836,0" size="200,45" valign="center" halign="left" foregroundColor="#00B6B6B6" backgroundColor="#18101214" font="Regular; 26" transparent="1" />
				<widget name="weatherPixmap" position="1065,7" size="30,30" alphatest="blend" />
				<widget name="temperature" position="1107,0" size="80,45" valign="center" halign="right" foregroundColor="#00B6B6B6" backgroundColor="#18101214" font="Regular; 26" transparent="1" />
				<widget name="feeltemperature" position="1175,0" size="80,45" valign="center" halign="right" foregroundColors="#00B6B6B6,#29abe2,#ff5555" backgroundColor="#18101214" font="Regular; 26" transparent="1" />
			</screen>""" % {"screen_name": PLUGIN_NAME, "imageDir": imageDir, "windPixmaps": windPixmaps, "secondInfoBarBackgroundColor": secondInfoBarBackgroundColor, "rainWidgets": rainWidgets}
		if not fileExists(tmpdir):
			os.mkdir(tmpdir)
		with open(tmpdir + "/skin.xml", "w") as f:
			f.write(self.skin)
		InfoBarExtra.__init__(self, session)
		Screen.__init__(self, session)
		for item in xml.etree.ElementTree.ElementTree(xml.etree.ElementTree.fromstring(self.skin)).getroot().findall('./widget'):
			name = item.attrib["name"]
			if "rainMultiPixmap" in name or name == "precipitation":
				self.hasRainWidget = True
			if "MultiPixmap" in name or "pixmaps" in item.attrib:
				self[name] = MultiPixmap()
			elif "Pixmap" in name or "pixmap" in item.attrib:
				self[name] = Pixmap()
			elif name == "feeltemperature" or "foregroundColors" in item.attrib:
				self[name] = MultiColorLabel()
			else:
				self[name] = Label()
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
		self.timer = eTimer()
		self.timer.callback.append(self.timerCB)
		global infoBarWeatherInstance
		infoBarWeatherInstance = self

	def timerCB(self):
		self.checkIfStale()
		InfoBarExtra.timerCB(self)

	def downloadRainCB(self, string):
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
				except KeyError:
					pass # some skinner removed the widget
			i += 1
		self.showWidgets(self.RAIN)

	def downloadIconCB(self, string):
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
			for x in self:
				if x[0] != '_' and "precipitation" not in x and "nfoBarBackground" not in x and "rainMultiPixmap" not in x and x != "weatherPixmap" and x != "zero" and x != "one" and x != "two" and x != "notconfigured":
					try:
						if x == 'sunrise' or x == 'sunset' or x == 'sunrisesetPixmap':
							attr = 'showsunriseset'
						elif x == 'humidity' or x == 'humidityPixmap':
							attr = 'showhumidity'
						elif x == 'weatherPixmap':
							attr = 'showicon'
						elif x == 'windspeedms' or x == 'beaufort' or x == 'winddirectionMultiPixmap':
							attr = 'showwind'
						else:
							attr = 'show' + x
						if hasattr(settings, attr) and getattr(settings, attr).value and how:
							if (windSpeedUnit == 1 and x == "windspeedms") or (windSpeedUnit != 1 and x == "beaufort"):
								continue
							self[x].show()
						else:
							self[x].hide()
					except (AttributeError, IndexError) as e:
						pass

	def hideWidgets(self, what):
		self.hideOrShowWidgets(False, what)

	def showWidgets(self, what):
		self.hideOrShowWidgets(True, what)

	def errback(self, message=None):
		print("[%s] error: %s" % (TAG, str(message)))

	def updateUI(self, string):
		try:
			with open(jsonFile, "r") as f:
				j = json.loads(f.read())
		except (IOError, ValueError) as e:
			return

		with self.lastUpdateLock:
			self.lastUpdate = datetime.datetime.now()

		h = j['days'][0]['hours']
		d = h[0]

		self.beaufort    = d['beaufort']
		self.windspeedms = d['windspeedms']

		x = {}
		x['regio']           = settings.locationname.value
		x['temperature']     = str(d['temperature'])
		x['feeltemperature'] = str(d['feeltemperature'])
		x['beaufort']        = str(d['beaufort'])
		x['windspeedms']     = str(int(round(d['windspeedms']))) if int(settings.windSpeedUnit.value) == 2 else str(int(round(d['windspeedms'] * 3.6)))
		x['humidity']        = str(d['humidity'])
		x['precipitation']   = str(d['precipitation'])

		if "weatherPixmap" in self and "iconcode" in d:
			iconurl = "https://www.buienradar.nl/resources/images/icons/weather/30x30/" + d["iconcode"] + ".png"
			filename = iconurl.split("/")[-1]
			self.iconfilepath = tmpdir + "/" + filename
			if not fileExists(self.iconfilepath):
				print("[%s] downloading %s to %s" % (TAG, str(iconurl), self.iconfilepath))
				downloadWithProgress(str(iconurl), self.iconfilepath).start().addCallback(self.downloadIconCB).addErrback(self.errback)
			else:
				try:
					self["weatherPixmap"].instance.setPixmapFromFile(str(self.iconfilepath))
					self["weatherPixmap"].show()
				except Exception as e:
					self["weatherPixmap"].hide()
					print("[%s] Exception: %s" % (TAG, e))
		if "winddirectionMultiPixmap" in self and "winddirection" in d:
			try:
				self["winddirectionMultiPixmap"].setPixmapNum(self.windDirections.index(d["winddirection"]))
				self["winddirectionMultiPixmap"].show()
			except IndexError:
				self["winddirectionMultiPixmap"].hide()
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
					if x[y] > x["temperature"]:
						self[y].setForegroundColorNum(2)
					elif x[y] < x["temperature"]:
						self[y].setForegroundColorNum(1)
					else:
						self[y].setForegroundColorNum(0)
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
		self.onShowHideSecondInfoBar(True)

	def _onHideSecondInfoBar(self):
		self.onShowHideSecondInfoBar(False)

	def reset(self):
		self["notconfigured"].hide()
		with self.lastUpdateLock:
			self.lastUpdate = datetime.datetime.min
		windSpeedUnit = int(settings.windSpeedUnit.value)
		if windSpeedUnit == 1:
			self["beaufort"].show()
			self["windspeedms"].hide()
			if hasattr(self, "beaufort"):
				self['beaufort'].setText(str(self.beaufort) + self.units["beaufort"])
			else:
				self['beaufort'].setText('')
		else:
			self.units["windspeedms"] = " " + _("km/h") if windSpeedUnit == 3 else " " + _("m/s")
			self["beaufort"].hide()
			self["windspeedms"].show()
			if hasattr(self, "windspeedms"):
				windspeed = str(int(round(self.windspeedms))) if int(settings.windSpeedUnit.value) == 2 else str(int(round(self.windspeedms * 3.6)))
				self['windspeedms'].setText(windspeed + self.units["windspeedms"])
			else:
				self['windspeedms'].setText('')

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
			downloadWithProgress(url, jsonFile).start().addCallback(self.updateUI)
			if self.hasRainWidget and settings.hasRain.value:
				lat = float(settings.locationlat.value)
				lon = float(settings.locationlon.value)
				url = rainForecastUrl % (lat, lon)
				print("[%s] downloading %s to %s" % (TAG, url, rainFile))
				downloadWithProgress(url, rainFile).start().addCallback(self.downloadRainCB)

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
		self.l.setFont(0, gFont("Regular", 28))
		self.l.setItemHeight(45)
		self.selection = selection

	@staticmethod
	def entry(locationid, locationname, province, country):
		l = [locationid]
		if desktopWidth > 1800:
			countryStart = 770
			countryWidth = 310
			provinceStart = 430
			provinceWidth = 310
			locationnameStart = 10
			locationnameWidth = 400
			itemHeight = 45
		else:
			countryStart = 480
			countryWidth = 175
			provinceStart = 295
			provinceWidth = 175
			locationnameStart = 10
			locationnameWidth = 275
			itemHeight = 25
		l.append((eListboxPythonMultiContent.TYPE_TEXT, countryStart,      0, countryWidth,      itemHeight, 0, RT_HALIGN_LEFT|RT_VALIGN_CENTER, country))
		l.append((eListboxPythonMultiContent.TYPE_TEXT, provinceStart,     0, provinceWidth,     itemHeight, 0, RT_HALIGN_LEFT|RT_VALIGN_CENTER, province))
		l.append((eListboxPythonMultiContent.TYPE_TEXT, locationnameStart, 0, locationnameWidth, itemHeight, 0, RT_HALIGN_LEFT|RT_VALIGN_CENTER, locationname))
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
					<widget name="province" position="1210,103" size="200,45" font="Regular; 28" />
					<widget name="country" position="1551,103" size="200,45" font="Regular; 28" />
					<widget name="locationList" position="780,153" size="1109,855" font="Regular; 28" itemHeight="45" scrollbarMode="showOnDemand" />
				</screen>"""
		elif desktopWidth > 1800:
			self.skin = """
				<screen name=\"""" + PLUGIN_NAME + """SelectLocation" position="center,center" size="1110,715">
					<widget name="city" position="20,9" size="200,45" font="Regular; 28" />
					<widget name="province" position="440,9" size="200,45" font="Regular; 28" />
					<widget name="country" position="781,9" size="200,45" font="Regular; 28" />
					<widget name="locationList" position="10,55" size="e-10,e-130" font="Regular; 28" itemHeight="45" scrollbarMode="showOnDemand" />
					<ePixmap pixmap="skin_default/buttons/key_ok.png" position="10,e-42" zPosition="0" size="35,25" transparent="1" alphatest="on" />
					<ePixmap pixmap="skin_default/buttons/red.png" position="55,e-50" zPosition="0" size="140,40" transparent="1" alphatest="on" />
					<ePixmap pixmap="skin_default/buttons/green.png" position="195,e-50" zPosition="0" size="140,40" transparent="1" alphatest="on" />
					<widget name="key_red" position="55,e-50" zPosition="1" size="140,40" font="Regular; 20" valign="center" halign="center" backgroundColor="#9f1313" transparent="1" />
					<widget name="key_green" position="195,e-50" zPosition="1" size="140,40" font="Regular; 20" valign="center" halign="center" backgroundColor="#1f771f" transparent="1" />
				</screen>"""
		else:
			self.skin = """
				<screen name=\"""" + PLUGIN_NAME + """SelectLocation" position="center,center" size="700,526">
					<widget name="city" position="10,4" size="200,45" font="Regular; 18" />
					<widget name="province" position="310,4" size="200,45" font="Regular; 18" />
					<widget name="country" position="520,4" size="200,45" font="Regular; 18" />
					<widget name="locationList" position="0,35" size="e-10,425" font="Regular; 18" itemHeight="25" scrollbarMode="showOnDemand" />
					<ePixmap pixmap="skin_default/buttons/key_ok.png" position="10,e-42" zPosition="0" size="35,25" transparent="1" alphatest="on" />
					<ePixmap pixmap="skin_default/buttons/red.png" position="55,e-50" zPosition="0" size="140,40" transparent="1" alphatest="on" />
					<ePixmap pixmap="skin_default/buttons/green.png" position="195,e-50" zPosition="0" size="140,40" transparent="1" alphatest="on" />
					<widget name="key_red" position="55,e-50" zPosition="1" size="140,40" font="Regular; 20" valign="center" halign="center" backgroundColor="#9f1313" transparent="1" />
					<widget name="key_green" position="195,e-50" zPosition="1" size="140,40" font="Regular; 20" valign="center" halign="center" backgroundColor="#1f771f" transparent="1" />
				</screen>"""
		self.session = session
		Screen.__init__(self, session)
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
			self.locationList.append(LocationList.entry(x["id"], name, province + provincecode, country + countrycode))
		self["city"] = Label(_("Location"))
		self["province"] = Label(_("State/province"))
		self["country"] = Label(_("Country"))
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

	locationid = settings.locationid.value
	hasRain = settings.hasRain.value
	locationname = settings.locationname.value
	locationlat = settings.locationlat.value
	locationlon = settings.locationlon.value

	def __init__(self, session):
		primarySkin = config.skin.primary_skin.value.split("/")[0]
		if primarySkin == "PLi-FullNightHD" or primarySkin == "PLi-FullHD" or primarySkin == "Pd1loi-HD-night":
			self.skin = """
				<screen name=\"""" + PLUGIN_NAME + """Setup" position="fill" flags="wfNoBorder">
					<panel name="PigTemplate"/>
					<widget name="description" position="30,570" size="720,300" itemHeight="38" font="Regular;30" valign="top"/>
					<panel name="ButtonRed"/>
					<panel name="ButtonGreen"/>
					<panel name="KeyOkTemplate"/>
					<widget name="config" position="780,120" size="1109,855" font="Regular; 28" itemHeight="45" scrollbarMode="showOnDemand" />
				</screen>"""
		elif desktopWidth > 1800:
			self.skin = """
				<screen name=\"""" + PLUGIN_NAME + """Setup" position="center,center" size="1110,715">
					<widget name="description" position="30,570" size="720,300" itemHeight="38" font="Regular;30" valign="top"/>
					<widget name="config" position="5,60" size="590,105" scrollbarMode="showOnDemand" />
					<ePixmap pixmap="skin_default/buttons/key_ok.png" position="10,e-42" zPosition="0" size="35,25" transparent="1" alphatest="on" />
					<ePixmap pixmap="skin_default/buttons/red.png" position="55,e-50" zPosition="0" size="140,40" transparent="1" alphatest="on" />
					<ePixmap pixmap="skin_default/buttons/green.png" position="195,e-50" zPosition="0" size="140,40" transparent="1" alphatest="on" />
					<widget name="key_red" position="55,e-50" zPosition="1" size="140,40" font="Regular; 20" valign="center" halign="center" backgroundColor="#9f1313" transparent="1" />
					<widget name="key_green" position="195,e-50" zPosition="1" size="140,40" font="Regular; 20" valign="center" halign="center" backgroundColor="#1f771f" transparent="1" />
				</screen>"""
		else:
			self.skin = """
				<screen name=\"""" + PLUGIN_NAME + """Setup" position="center,center" size="700,526">
					<widget name="description" position="30,570" size="720,300" itemHeight="38" font="Regular;30" valign="top"/>
					<widget name="config" position="5,60" size="590,105" scrollbarMode="showOnDemand" />
					<ePixmap pixmap="skin_default/buttons/key_ok.png" position="10,e-42" zPosition="0" size="35,25" transparent="1" alphatest="on" />
					<ePixmap pixmap="skin_default/buttons/red.png" position="55,e-50" zPosition="0" size="140,40" transparent="1" alphatest="on" />
					<ePixmap pixmap="skin_default/buttons/green.png" position="195,e-50" zPosition="0" size="140,40" transparent="1" alphatest="on" />
					<widget name="key_red" position="55,e-50" zPosition="1" size="140,40" font="Regular; 20" valign="center" halign="center" backgroundColor="#9f1313" transparent="1" />
					<widget name="key_green" position="195,e-50" zPosition="1" size="140,40" font="Regular; 20" valign="center" halign="center" backgroundColor="#1f771f" transparent="1" />
				</screen>"""
		self.session = session
		Screen.__init__(self, session)
		self.setTitle(_("InfoBarWeather %(version)s setup" % {"version": VERSION}))
		ConfigListScreen.__init__(self, [], session=session) #, on_change=self.changed)
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

	def initConfiglist(self):
		settings.enabled.addNotifier(self.buildConfiglist, initial_call=False)
		settings.showrain.addNotifier(self.buildConfiglist, initial_call=False)
		self.buildConfiglist()

	def deinitConfig(self):
		settings.enabled.removeNotifier(self.buildConfiglist)
		settings.showrain.removeNotifier(self.buildConfiglist)

	def buildConfiglist(self, configElement=None):
		cfgList = [getConfigListEntry(_('Enabled'), settings.enabled)]
		if settings.enabled.value:
			cfgList.extend([
				getConfigListEntry(_('Location'), settings.locationname2, _("Press OK to open location search.")),
				getConfigListEntry(_('Wind speed unit'), settings.windSpeedUnit, _("Display wind speed as BFT, m/s or km/h.")),
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
		reason = 0 if settings.enabled.value else 1
		start(SETTINGSCHANGE, reason=reason)
		if settings.enabled.value and infoBarWeatherInstance is not None:
			infoBarWeatherInstance.reset()

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
		downloadWithProgress(url, tmpdir + '/locations.json').start().addCallback(self.downloadLocationsSuccessCB).addErrback(self.downloadLocationsFailureCB)

	def downloadLocationsSuccessCB(self, string):
		self.session.openWithCallback(self.selectLocationScreenCB, SelectLocationScreen)
		self["config"].show()
		self["description"].show()

	def downloadLocationsFailureCB(self, string):
		self.session.open(MessageBox, _("Could not download location data."), MessageBox.TYPE_ERROR)
		self["config"].show()
		self["description"].show()

	def selectLocationScreenCB(self, locationid=None, country=None, hasRain=None, locationname=None, locationlat=None, locationlon=None):
		if locationid is not None:
			self.locationid = locationid
			self.country = country
			prevHasRain = self.hasRain
			self.hasRain = hasRain
			self.locationname = locationname
			self.locationlat = locationlat
			self.locationlon = locationlon
			settings.locationname2.setCurrentText(locationname)
			if hasRain != prevHasRain:
				self.buildConfiglist()


def setup(session, **kwargs):
	global session_
	session_ = session
	session_.open(SetupScreen)

session_ = None
started = False
baseInfoBarShowHide__init__ = None
InfoBarWeatherDialog = None
InfoBarWeatherDialog_onShowInfoBar = None

def newInfoBarShowHide__init__(self):
	global InfoBarWeatherDialog, InfoBarWeatherDialog_onShowInfoBar
	InfoBarWeatherDialog = self.session.instantiateDialog(InfoBarWeather)
	if baseInfoBarShowHide__init__:
		baseInfoBarShowHide__init__(self)
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
				if InfoBar.instance:
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
