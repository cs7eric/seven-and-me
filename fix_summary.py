content = open(r'E:\project-repo\mp4-to-word\polisher.py', 'r', encoding='utf-8').read()
old = """summary_str = (
                        f"【核心内容】{summary['核心内容']}\n\n"
                        f"【关键要点】\n" + "\n".join(f"• {p}" for p in summary['关键要点']) + "\n\n"
                        f"【待办事项】\n" + "\n".join(f"☐ {t}" for t in summary['待办事项'])
                    )"""
new = """summary_str = (
                        f"【核心内容】{summary['核心内容']}\n\n"
                        f"【关键要点】\n" + "\n".join(f"• {p}" for p in summary['关键要点'])
                    )"""
if old in content:
    content = content.replace(old, new)
    open(r'E:\project-repo\mp4-to-word\polisher.py', 'w', encoding='utf-8').write(content)
    print('replaced ok')
else:
    print('not found, searching...')
    idx = content.find('summary_str = (')
    if idx >= 0:
        print(repr(content[idx:idx+400]))
    else:
        print('summary_str not found at all')