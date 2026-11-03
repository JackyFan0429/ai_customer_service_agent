"""Bounded topic references, with explicit pauses kept out of current actions."""

import re


NON_TOPICS = {'greeting', 'unknown', 'resolved', 'resolution_check'}
PAUSE = re.compile(r'^(?:好[的吧]?[,，]?\s*)?(?:先|暂时|这次|现在|目前)?(?:不再|不要再|不要|不想|不|别再|别)(?:谈|讲|说|问|聊|管|处理|考虑|讨论|纠结|看|查|提)|^(?:不是|不问|不需要处理|不用处理)')
SWITCH = re.compile(r'换(?:一)?个(?:新)?问题\s*[:：,，]?|(?:现在|接着|再|然后)?回到|(?:现在|先)(?:只)?(?:问|看|说)(?:一下)?|我问的是')
RETURN = re.compile(r'回到|回头(?:再)?(?:说|问)|再问(?:之前|原来)|切回')


def keywords(text, patterns):
    technical = re.sub(r'用不了(?:这么多|那么多|这许多)|用不完', '', text)
    return [key for key, pattern in patterns.items()
            if re.search(pattern, technical if key == 'technical' else text, re.I)]


def topic_history(state):
    result = state.get('topic_history', [])
    if not result:
        active = [i for i in state.get('active_intents', state.get('intents', [])) if i not in NON_TOPICS]
        result = [{'intents': active, 'question': state.get('last_question', '')}] if active else []
    return result


def focus_question(query, state, patterns):
    """Resolve only the user's topic reference; old facts never become new facts."""
    clauses = re.split(r'[。；;\n，,]|(?=而是|我问的是|换(?:一)?个(?:新)?问题|回到)', query)
    kept, excluded = [], set()
    for clause in clauses:
        clause = clause.strip()
        if PAUSE.search(clause):
            excluded.update(keywords(clause, patterns))
        elif clause:
            kept.append(clause)
    focused = '，'.join(kept)
    switch = SWITCH.search(focused)
    if switch:
        excluded.update(keywords(focused[:switch.start()], patterns))
        focused = focused[switch.start():]
    explicit = keywords(focused, patterns)
    excluded.difference_update(explicit)
    history = topic_history(state)
    distinct = []
    for topic in history:
        if not any(set(t['intents']) == set(topic['intents']) for t in distinct):
            distinct.append(topic)
    reference, ambiguous = None, False
    returning = bool(RETURN.search(focused))
    if returning and not explicit:
        if re.search(r'最开始|一开始|第一个|最早', focused):
            reference = history[0] if history else None
        elif re.search(r'刚才|上一个|前一个', focused) or len(distinct) == 2:
            current = set(state.get('active_intents', []))
            reference = next((t for t in reversed(history) if set(t['intents']) != current), None)
        elif len(distinct) > 2:
            ambiguous = True
        if reference:
            explicit = [i for i in reference['intents'] if i not in excluded]
        elif not ambiguous:
            ambiguous = True
    return {'message': focused, 'intents': explicit, 'excluded_intents': sorted(excluded),
            'reference_question': reference['question'] if reference else '',
            'explicit_switch': bool(switch or excluded or returning), 'ambiguous': ambiguous,
            'known_topics': [t['intents'] for t in distinct]}


def remember_topic(state, query, intents):
    history = list(topic_history(state))
    meaningful = [i for i in intents if i not in NON_TOPICS]
    if meaningful and (not history or set(history[-1]['intents']) != set(meaningful)):
        history.append({'intents': meaningful, 'question': query[:500]})
    # Retain the first reference and recent switches without unbounded prompts.
    return history[:1] + history[-7:] if len(history) > 8 else history
