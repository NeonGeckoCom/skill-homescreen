import datetime
import os
import time
import requests

from os import path
from mycroft_bus_client import Message
from neon_utils.logger import LOG

from mycroft.skills.core import resting_screen_handler, intent_file_handler, MycroftSkill
from mycroft.skills.skill_loader import load_skill_module
from mycroft.skills.skill_manager import SkillManager
from mycroft.skills.api import SkillApi


class OVOSHomescreen(MycroftSkill):
    # The constructor of the skill, which calls MycroftSkill's constructor
    def __init__(self):
        super(OVOSHomescreen, self).__init__(name="OVOSHomescreen")
        self.skill_manager = None
        self.notifications_model = []
        self.notifications_storage_model = []
        self.def_wallpaper_folder = path.dirname(__file__) + '/ui/wallpapers/'
        self.loc_wallpaper_folder = self.file_system.path + '/wallpapers/'
        self.selected_wallpaper = self.settings.get("wallpaper") or "default.jpg"
        self.wallpaper_collection = []
        self.rtlMode = 1 if self.config_core.get("rtl", False) else 0

        # Populate skill IDs to use for data sources
        self.weather_skill = self.settings.get("weather_skill") or "skill-weather.openvoiceos"
        self.datetime_skill = self.settings.get("datetime_skill") or "skill-date-time.mycroftai"
        self.skill_info_skill = self.settings.get("examples_skill") or "ovos-skills-info.openvoiceos"
        self.weather_api = None
        self.datetime_api = None
        self.skill_info_api = None

    def initialize(self):
        now = datetime.datetime.now()
        callback_time = datetime.datetime(
            now.year, now.month, now.day, now.hour, now.minute
        ) + datetime.timedelta(seconds=60)
        self.schedule_repeating_event(self.update_dt, callback_time, 10)
        self.skill_manager = SkillManager(self.bus)

        # Handler Registration For Notifications
        self.add_event("homescreen.notification.set",
                       self.handle_display_notification)
        self.add_event("homescreen.wallpaper.set",
                       self.handle_set_wallpaper)
        self.gui.register_handler("homescreen.notification.set",
                                  self.handle_display_notification)
        self.gui.register_handler("homescreen.notification.pop.clear",
                                  self.handle_clear_notification_data)
        self.gui.register_handler("homescreen.notification.pop.clear.delete",
                                  self.handle_clear_delete_notification_data)
        self.gui.register_handler("homescreen.notification.storage.clear",
                                  self.handle_clear_notification_storage)
        self.gui.register_handler("homescreen.notification.storage.item.rm",
                                  self.handle_clear_notification_storage_item)

        self.add_event("mycroft.ready", self.handle_mycroft_ready)
        
        if not self.file_system.exists("wallpapers"):
            os.mkdir(path.join(self.file_system.path, "wallpapers"))
        
        self.collect_wallpapers()
        self._load_skill_apis()

        self.bus.emit(Message("mycroft.device.show.idle"))

    #####################################################################
    # Homescreen Registration & Handling

    @resting_screen_handler("OVOSHomescreen")
    def handle_idle(self, _):
        LOG.debug('Activating Time/Date resting page')
        self.gui['wallpaper_path'] = self.check_wallpaper_path(self.selected_wallpaper)
        self.gui['selected_wallpaper'] = self.selected_wallpaper
        self.gui['notification'] = {}
        self.gui["notification_model"] = {
            "storedmodel": self.notifications_storage_model,
            "count": len(self.notifications_storage_model),
        }
        self._load_skill_apis()
        self.update_dt()
        self.update_weather()
        self.update_examples()

        self.gui['rtl_mode'] = self.rtlMode
        self.gui.show_page("idle.qml")

    def update_examples(self):
        """
        Loads or updates skill examples via the skill_info_api.
        """
        if not self.skill_info_api:
            LOG.warning(f"Requested update before API's loaded!")
            self._load_skill_apis()
        try:
            self.gui['skill_examples'] = {"examples": self.skill_info_api.skill_info_examples()}
        except Exception as e:
            LOG.error(e)

    def update_dt(self):
        """
        Loads or updates date/time via the datetime_api.
        """
        if not self.datetime_api:
            LOG.warning(f"Requested update before API's loaded!")
            self._load_skill_apis()
        self.gui["time_string"] = self.datetime_api.get_display_current_time()
        self.gui["date_string"] = self.datetime_api.get_display_date()
        self.gui["weekday_string"] = self.datetime_api.get_weekday()
        self.gui['day_string'], self.gui["month_string"] = self._split_month_string(self.datetime_api.get_month_date())
        self.gui["year_string"] = self.datetime_api.get_year()

    def update_weather(self):
        """
        Loads or updates weather via the weather_api.
        """
        try:
            current_weather_report = self.weather_api.get_current_weather_homescreen()
            self.gui["weather_code"] = current_weather_report.get("weather_code")
            self.gui["weather_temp"] = current_weather_report.get("weather_temp")
        except Exception as e:
            LOG.error(f"Failed To Fetch Weather Report: {e}")

    #####################################################################
    # Wallpaper Manager

    def collect_wallpapers(self):
        def_wallpaper_collection, loc_wallpaper_collection = None, None
        for dirname, dirnames, filenames in os.walk(self.def_wallpaper_folder):
            def_wallpaper_collection = filenames
        
        for dirname, dirnames, filenames in os.walk(self.loc_wallpaper_folder):
            loc_wallpaper_collection = filenames
        
        self.wallpaper_collection = def_wallpaper_collection + loc_wallpaper_collection

    @intent_file_handler("change.wallpaper.intent")
    def change_wallpaper(self, _):
        # Get Current Wallpaper idx
        current_idx = self.get_wallpaper_idx(self.selected_wallpaper)
        collection_length = len(self.wallpaper_collection) - 1
        if not current_idx == collection_length:
            fidx = current_idx + 1
            self.selected_wallpaper = self.wallpaper_collection[fidx]
            self.settings["wallpaper"] = self.wallpaper_collection[fidx]

        else:
            self.selected_wallpaper = self.wallpaper_collection[0]
            self.settings["wallpaper"] = self.wallpaper_collection[0]

        self.gui['wallpaper_path'] = self.check_wallpaper_path(self.selected_wallpaper)
        self.gui['selected_wallpaper'] = self.selected_wallpaper

    def get_wallpaper_idx(self, filename):
        try:
            index_element = self.wallpaper_collection.index(filename)
            return index_element
        except ValueError:
            return None
        
    def handle_set_wallpaper(self, message):
        image_url = message.data.get("url", "")
        now = datetime.datetime.now()
        setname = "wallpaper-" + now.strftime("%H%M%S") + ".jpg"
        if image_url:
            print(image_url)
            response = requests.get(image_url)
            with self.file_system.open(path.join("wallpapers", setname), "wb") as my_file:
                my_file.write(response.content)
                my_file.close()
            self.collect_wallpapers()
            cidx = self.get_wallpaper_idx(setname)
            self.selected_wallpaper = self.wallpaper_collection[cidx]
            self.settings["wallpaper"] = self.wallpaper_collection[cidx]

            self.gui['wallpaper_path'] = self.check_wallpaper_path(setname)
            self.gui['selected_wallpaper'] = self.selected_wallpaper
            
    def check_wallpaper_path(self, wallpaper):
        file_def_check = self.def_wallpaper_folder + wallpaper
        file_loc_check = self.loc_wallpaper_folder + wallpaper
        if path.exists(file_def_check):
            return self.def_wallpaper_folder
        elif path.exists(file_loc_check):
            return self.loc_wallpaper_folder

    #####################################################################
    # Manage notifications

    def handle_display_notification(self, message):
        """ Get Notification & Action """
        notification_message = {
            "sender": message.data.get("sender", ""),
            "text": message.data.get("text", ""),
            "action": message.data.get("action", ""),
            "type": message.data.get("type", ""),
        }
        if notification_message not in self.notifications_model:
            self.notifications_model.append(notification_message)
            self.gui["notifcation_counter"] = len(self.notifications_model)
            self.gui["notification"] = notification_message
            time.sleep(2)
            self.bus.emit(Message("homescreen.notification.show"))

    def handle_clear_notification_data(self, message):
        """ Clear Pop Notification """
        notification_data = message.data.get("notification", "")
        self.notifications_storage_model.append(notification_data)
        for i in range(len(self.notifications_model)):
            if (
                self.notifications_model[i]["sender"] == notification_data["sender"]
                and self.notifications_model[i]["text"] == notification_data["text"]
            ):
                if not len(self.notifications_model) > 0:
                    del self.notifications_model[i]
                    self.notifications_model = []
                else:
                    del self.notifications_model[i]
                break

        self.gui["notification_model"] = {
            "storedmodel": self.notifications_storage_model,
            "count": len(self.notifications_storage_model),
        }
        self.gui["notification"] = {}

    def handle_clear_delete_notification_data(self, message):
        """ Clear Pop Notification & Delete Notification Data """
        notification_data = message.data.get("notification", "")
        for i in range(len(self.notifications_model)):
            if (
                self.notifications_model[i]["sender"] == notification_data["sender"]
                and self.notifications_model[i]["text"] == notification_data["text"]
            ):
                if not len(self.notifications_model) > 0:
                    del self.notifications_model[i]
                    self.notifications_model = []
                else:
                    del self.notifications_model[i]
                break

    def handle_clear_notification_storage(self, _):
        """ Clear All Notification Storage Model """
        self.notifications_storage_model = []
        self.gui["notification_model"] = {
            "storedmodel": self.notifications_storage_model,
            "count": len(self.notifications_storage_model),
        }

    def handle_clear_notification_storage_item(self, message):
        """ Clear Single Item From Notification Storage Model """
        notification_data = message.data.get("notification", "")
        for i in range(len(self.notifications_storage_model)):
            if (
                self.notifications_storage_model[i]["sender"]
                == notification_data["sender"]
                and self.notifications_storage_model[i]["text"]
                == notification_data["text"]
            ):
                self.notifications_storage_model.pop(i)
                self.gui["notification_model"] = {
                    "storedmodel": self.notifications_storage_model,
                    "count": len(self.notifications_storage_model),
                }

    def stop(self):
        pass

    def shutdown(self):
        self.cancel_all_repeating_events()

    def handle_mycroft_ready(self, _):
        self._load_skill_apis()

    def _load_skill_apis(self):
        """
        Loads weather, date/time, and examples skill APIs
        """
        try:
            if not self.weather_api:
                self.weather_api = SkillApi.get(self.weather_skill)
        except Exception as e:
            LOG.error(f"Failed To Import Weather Skill: {e}")

        try:
            if not self.skill_info_api:
                self.skill_info_api = SkillApi.get(self.skill_info_skill)
        except Exception as e:
            LOG.error(f"Failed To Import OVOS Info Skill: {e}")

        # Import Date Time Skill As Date Time Provider
        try:
            self.datetime_api = SkillApi.get(self.datetime_skill)
        except Exception as e:
            # TODO: Depreciate this
            LOG.error(f"Failed to import DateTime Skill: {e}")
            try:
                root_dir = self.root_dir.rsplit("/", 1)[0]
                time_date_path = str(root_dir) + "/date-time.neon/__init__.py"
                time_date_id = "datetimeskill"
                datetimeskill = load_skill_module(time_date_path, time_date_id)
                from datetimeskill import TimeSkill

                self.datetime_api = TimeSkill()
            except Exception as e:
                LOG.error(f"Failed To Import DateTime Skill: {e}")

    def _split_month_string(self, month_date: str) -> list:
        """
        Splits a month+date string into month and date (i.e. "August 06" -> ["August", "06"])
        :param month_date: formatted month and day of month ("August 06" or "06 August")
        :return: [day, month]
        """
        month_string = month_date.split(" ")
        if self.config_core.get('date_format') == 'MDY':
            day_string = month_string[1]
            month_string = month_string[0]
        else:
            day_string = month_string[0]
            month_string = month_string[1]

        return [day_string, month_string]


def create_skill():
    return OVOSHomescreen()
