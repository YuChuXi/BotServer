#!/usr/bin/env python3
"""
导入绑定信息脚本
从命令次数记录.json导入绑定信息到Player.json
"""
import json
from pathlib import Path


def is_bedrock_player(player_name: str) -> bool:
    """
    判断是否为基岩版玩家（基岩版用户名包含点）
    
    Args:
        player_name: 玩家名
        
    Returns:
        True 如果是基岩版，False 如果是Java版
    """
    return '.' in player_name


def import_bindings(source_file: str, target_file: str = './Data/Player.json', max_bindings_per_qq: int = 1):
    """
    从源文件导入绑定信息（自动识别Java版和基岩版）
    
    Args:
        source_file: 源JSON文件路径
        target_file: 目标JSON文件路径
        max_bindings_per_qq: 每个QQ最大绑定数量
    """
    source_path = Path(source_file)
    if not source_path.exists():
        print(f'错误: 源文件不存在: {source_file}')
        return
    
    target_path = Path(target_file)
    
    # 加载目标文件
    if target_path.exists():
        try:
            with open(target_path, 'r', encoding='utf-8') as f:
                target_data = json.load(f)
        except Exception as e:
            print(f'错误: 读取目标文件失败: {e}')
            return
    else:
        target_data = {'bounds': {}, 'blacklist': []}
    
    # 加载源文件
    try:
        with open(source_path, 'r', encoding='utf-8') as f:
            source_data = json.load(f)
    except Exception as e:
        print(f'错误: 读取源文件失败: {e}')
        return
    
    # 提取绑定信息
    bindings_data = source_data.get('cmdTimes', {}).get('bindWl', {})
    
    if not bindings_data:
        print('警告: 未找到绑定数据 (cmdTimes.bindWl)')
        return
    
    bounds = target_data.setdefault('bounds', {})
    blacklist = target_data.setdefault('blacklist', [])
    
    imported_java = 0
    imported_bedrock = 0
    skipped_count = 0
    
    for qq, info in bindings_data.items():
        # 获取记录值（玩家名列表）
        player_names = info.get('记录值', [])
        
        if not player_names:
            continue
        
        # 检查黑名单
        if qq in blacklist:
            print(f'跳过: QQ {qq} 在黑名单中')
            skipped_count += 1
            continue
        
        # 获取现有绑定
        existing = bounds.get(qq, {'bedrock': [], 'java': []})
        existing_java = existing.get('java', [])
        existing_bedrock = existing.get('bedrock', [])
        current_count = len(existing_java) + len(existing_bedrock)
        
        # 处理所有玩家名
        for player_name in player_names:
            if not player_name:
                continue
            
            # 判断版本
            is_bedrock = is_bedrock_player(player_name)
            version = 'bedrock' if is_bedrock else 'java'
            
            # 检查是否已存在
            if is_bedrock:
                if player_name in existing_bedrock:
                    continue
            else:
                if player_name in existing_java:
                    continue
            
            # 检查绑定数量限制
            if current_count >= max_bindings_per_qq:
                print(f'跳过: QQ {qq} 绑定数量已达上限 ({max_bindings_per_qq})，跳过玩家 {player_name}')
                skipped_count += 1
                continue
            
            # 添加绑定
            if qq not in bounds:
                bounds[qq] = {'bedrock': [], 'java': []}
            
            target_list = bounds[qq][version]
            if player_name not in target_list:
                target_list.append(player_name)
                current_count += 1
                if is_bedrock:
                    imported_bedrock += 1
                else:
                    imported_java += 1
                print(f'导入: QQ {qq} -> {version}版玩家 {player_name}')
    
    # 保存结果
    try:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        with open(target_path, 'w', encoding='utf-8') as f:
            json.dump(target_data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f'错误: 保存目标文件失败: {e}')
        return
    
    total_imported = imported_java + imported_bedrock
    print(f'\n导入完成: Java版 {imported_java} 条，基岩版 {imported_bedrock} 条，共 {total_imported} 条，跳过 {skipped_count} 条')


if __name__ == '__main__':
    source_file = '/home/yuchuxi/Desktop/tmp/命令次数记录.json'
    target_file = './Data/Player.json'
    max_bindings_per_qq = 1
    
    print(f'开始从 {source_file} 导入绑定信息...')
    print('自动识别Java版和基岩版（基岩版用户名包含点）')
    print(f'目标文件: {target_file}')
    print(f'每个QQ最大绑定数量: {max_bindings_per_qq}\n')
    
    import_bindings(source_file, target_file, max_bindings_per_qq)
    
    print('\n导入完成！')
