import os
import pickle
from PySide6.QtCore import QDateTime, QByteArray, QBuffer


def save_game(controller):
    settings = controller.story_data.get("settings", {"window_title": "GalPie", "identify_code": ""})
    data = [
        settings.get("window_title", "GalPie").replace(" ", "-").replace("_", "+"),
        settings.get("identify_code", "").replace(" ", "-").replace("_", "+"),
        None,
        controller.story_data.get("story_and_position", {}).get("storyline_id", None),
        controller.current_storyline_id,
        str(controller.current_page - 1),
        None,
        None,
        QDateTime.currentDateTime().toString("yyyy-MM-dd"),
        QDateTime.currentDateTime().toString("HH-mm-ss")
    ]
    img = controller.main_window.grab()
    byte_array = QByteArray()
    buffer = QBuffer(byte_array)
    buffer.open(QBuffer.WriteOnly)
    img.save(buffer, "PNG")
    data[2] = byte_array.data()
    page = controller.current_page - 1
    page_content = controller.story_data.get("story_and_position", {}).get("story", {}).get(
        controller.current_storyline_id, {}).get(str(page), [{}])[0].get("content", None)
    if page_content:
        if "speaking" in page_content:
            data[6] = page_content.get("speaking", None)
        else:
            data[6] = page_content.get("speaking_name", None)
        data[7] = page_content.get("words", None)
    if not os.path.exists("saves"):
        os.mkdir("saves")
    with open(f"./saves/{data[0]}_{data[1]}_{data[-2]}_{data[-1]}.gpsave", "wb") as f:
        pickle.dump(data, f)


def load_save(controller, load_file_name=None):
    if not load_file_name:
        save_files = get_this_story_saves_new_to_old(controller)
        with open("./saves/" + save_files[0], "rb") as f:
            data = pickle.load(f)
        if data[3]:
            controller.story_data["story_and_position"]["storyline_id"] = data[3]
        controller.current_storyline_id = data[4]
        controller.current_page = int(data[5])
        controller.current_scene_index = 0
        scene = build_last_scene(controller)
        controller.play_current_page(specify_scene=scene)
        controller.play_current_page()
        return


def build_last_scene(controller):
    page = controller.current_page
    scene = None
    story_data = controller.story_data
    current_storyline_id = controller.current_storyline_id
    story = story_data.get("story_and_position", {}).get("story", {}).get(current_storyline_id, {})
    first_page = next(iter(story), None)
    if not first_page:
        first_page = str(page)
    current_storyline_story = story
    now_scene = current_storyline_story.get(str(page), {})
    now_scene_clear_all = False
    while scene is None and str(page) != first_page and not now_scene_clear_all:
        page -= 1
        now_scene = current_storyline_story.get(str(page), {})
        for i in now_scene:
            if i.get("clear_all", False):
                scene = now_scene
    if page != controller.current_page:
        page -= 1
    while page != controller.current_page:
        page += 1
        now_scene = current_storyline_story.get(str(page), {})
        for i in now_scene:
            if i.get("bg", None):
                scene[0]["bg"] = i.get("bg", None)
            if i.get("characters", None):
                scene[0]["characters"] = i.get("characters", None)
                for j in i.get("characters", None):
                    if i["characters"][j].get("animate", None):
                        for k in i["characters"][j].get("animate", None):
                            for l in k:
                                if l.get("zoom", None):
                                    scene[0]["characters"][j]["zoom"] = l.get("zoom", None)
                                if l.get("move", None):
                                    now_pos = scene[0]["characters"][j]["pos"]
                                    animate_pos = l.get("move", [[0, 0]]) + [now_pos]
                                    scene[0]["characters"][j]["pos"] = list(map(lambda *args: sum(args), *animate_pos))
    if scene:
        scene = scene[0]
        scene["clear_all"] = True
        if not current_storyline_story.get(str(controller.current_page), [{}])[0].get("change", None) and scene.get(
                "change", None):
            del scene["change"]
        if "characters" in scene:
            for i in scene["characters"]:
                if "animate" in scene["characters"][i]:
                    del scene["characters"][i]["animate"]
        scene["content"] = {}
        scene["content"]["speaking"] = {}
        scene["content"]["words"] = {}
        for i in controller.story_data["settings"]["language"]:
            scene["content"]["speaking"][i] = ""
            scene["content"]["words"][i] = ""
    return scene


def get_this_story_saves_new_to_old(controller, save_dir="./saves", content_check=False):
    settings = controller.story_data.get("settings", {"window_title": "GalPie", "identify_code": ""})
    story_name = settings.get("window_title", "GalPie").replace(" ", "-").replace("_", "+")
    story_id = settings.get("identify_code", "").replace(" ", "-").replace("_", "+")
    result = []
    processing = {}
    if content_check:
        for i in os.listdir(save_dir):
            if os.path.splitext(i)[-1] == ".gpsave":
                with open(i, "rb") as f:
                    data = pickle.load(f)
                if data[0] == story_name and data[1] == story_id:
                    time_number_str = data[-2].replace("-", "") + data[-1].replace("-", "")
                    result.append(int(time_number_str))
                    processing[time_number_str] = i
    else:
        for i in os.listdir(save_dir):
            file_name_check = i.split("_")
            if os.path.splitext(i)[-1] == ".gpsave" and file_name_check[0] == story_name and file_name_check[1] == story_id:
                time_number_str = file_name_check[-2].replace("-", "") + file_name_check[-1][0:-7].replace("-", "")
                result.append(int(time_number_str))
                processing[time_number_str] = i
    result.sort(reverse=True)
    for i in range(len(result)):
        result[i] = processing[str(result[i])]
    return result