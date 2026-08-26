def load_ui_settings_from_data(main_window):
    story_data = main_window.controller.story_data
    if not story_data or "ui" not in story_data:
        print("使用默认UI设置")
        return
    ui_data = story_data["ui"]
    if "chatbox_and_words_position" in ui_data:
        chatbox_data = ui_data["chatbox_and_words_position"]
        if "chatbox" in chatbox_data:
            main_window.ui_settings["chatbox_style"] = chatbox_data["chatbox"]
            print(f"加载字幕框样式: {chatbox_data['chatbox']}")
        if "name_show_region" in chatbox_data:
            main_window.ui_settings["name_show_region"] = chatbox_data["name_show_region"]
            print(f"加载名字显示区域: {main_window.ui_settings['name_show_region']}")
        if "words_show_region" in chatbox_data:
            main_window.ui_settings["words_show_region"] = chatbox_data["words_show_region"]
            print(f"加载文本显示区域: {main_window.ui_settings['words_show_region']}")
        if "text_color" in chatbox_data:
            main_window.ui_settings["text_color"] = chatbox_data["text_color"]
            print(f"加载文本颜色: {main_window.ui_settings['text_color']}")
        if "readed_text_color" in chatbox_data:
            main_window.ui_settings["readed_text_color"] = chatbox_data["readed_text_color"]
            print(f"加载已读文本颜色: {main_window.ui_settings['readed_text_color']}")
    # ui.bottom_menu：底部菜单（剧情中对话框下方紧贴窗口底部的菜单条）
    if "bottom_menu" in ui_data:
        main_window.ui_settings["bottom_menu"] = ui_data["bottom_menu"]
        print(f"加载底部菜单配置: {main_window.ui_settings['bottom_menu']}")
    else:
        main_window.ui_settings["bottom_menu"] = None