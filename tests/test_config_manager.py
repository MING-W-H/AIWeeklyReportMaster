# -*- coding: utf-8 -*-
"""config_manager.validate_config 的单元测试。"""
import copy

from config_manager import DEFAULT_CONFIG, validate_config


def _valid_config() -> dict:
    """返回一份通过校验的合法配置（默认配置）。"""
    return copy.deepcopy(DEFAULT_CONFIG)


def test_default_config_passes_validation():
    assert validate_config(_valid_config()) == []


def test_unknown_top_level_field_reports_error():
    config = _valid_config()
    config["apikey"] = "sk-xxx"
    errors = validate_config(config)
    assert len(errors) == 1
    assert "config" in errors[0]
    assert "未知字段" in errors[0]
    assert "apikey" in errors[0]


def test_unknown_field_suggests_similar_name():
    # 把 provider 写成 apikey 时给出相近字段提示
    config = _valid_config()
    config["providers"]["minimax"]["apikey"] = "sk-xxx"
    errors = validate_config(config)
    assert any("apikey" in e and "api_key" in e for e in errors)


def test_wrong_type_string_for_int_field():
    config = _valid_config()
    config["tokens_to_generate"] = "4096"  # 字符串而非整数
    errors = validate_config(config)
    assert any("tokens_to_generate" in e and "类型错误" in e for e in errors)


def test_wrong_type_nested_section():
    config = _valid_config()
    config["email"]["smtp_port"] = "465"
    errors = validate_config(config)
    assert any("email.smtp_port" in e and "类型错误" in e for e in errors)


def test_bool_is_not_acceptable_as_int():
    # bool 是 int 的子类，temperature 填 true 应报错
    config = _valid_config()
    config["temperature"] = True
    errors = validate_config(config)
    assert any("temperature" in e and "布尔值" in e for e in errors)


def test_invalid_enum_value():
    config = _valid_config()
    config["provider"] = "gpt"
    errors = validate_config(config)
    assert any("provider" in e and "取值非法" in e for e in errors)


def test_invalid_send_weekday_range():
    config = _valid_config()
    config["crm_reminder"]["send_weekday"] = 7  # 0-6 之外
    errors = validate_config(config)
    assert any("crm_reminder.send_weekday" in e and "取值非法" in e for e in errors)


def test_custom_provider_key_allowed():
    config = _valid_config()
    config["providers"]["my_llm"] = {
        "api_key": "sk-xxx",
        "base_url": "https://example.com/v1/chat/completions",
        "model": "m1",
        "thinking_param": None,
        "max_tokens_field": "max_tokens",
    }
    assert validate_config(config) == []


def test_custom_notification_template_allowed():
    config = _valid_config()
    config["notification"]["templates"]["my_custom"] = {
        "title": "自定义",
        "template": "正文 {footer}",
    }
    assert validate_config(config) == []


def test_unknown_field_in_provider_reports_error():
    config = _valid_config()
    config["providers"]["minimax"]["timeout"] = 30  # 该位置无此字段
    errors = validate_config(config)
    assert any("minimax" in e and "未知字段" in e and "timeout" in e for e in errors)


def test_list_item_wrong_type():
    config = _valid_config()
    config["email"]["recipients"] = ["a@example.com", 123]
    errors = validate_config(config)
    assert any("recipients[1]" in e and "类型错误" in e for e in errors)


def test_empty_string_values_pass():
    # api_key 等留空（首次运行模板）不应误报
    config = _valid_config()
    config["providers"]["minimax"]["api_key"] = ""
    config["crm"]["token"] = ""
    assert validate_config(config) == []


def test_multiple_errors_collected_together():
    config = _valid_config()
    config["timeout"] = "abc"
    config["email"]["smtp_host"] = 123
    errors = validate_config(config)
    assert len(errors) == 2
    assert any("timeout" in e for e in errors)
    assert any("email.smtp_host" in e for e in errors)
