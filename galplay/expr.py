"""安全表达式：条件与赋值。

语法（各引擎的条件写法都先翻成这一种）：
  字面量   123  -4  "abc"  'abc'  true false
  变量     f.name（本局变量，随存档走）  s.name（系统变量，跨周目，按 agent 存）
  运算     + - * / %   == != < <= > >=   && || !   and or not   括号
赋值语句：  f.x = 1 ；  s.clear_a = 1 ；  f.n += 2   （多条用 ; 分隔）
未定义变量按 0 处理（和多数 ADV 引擎一致）。
"""
import ast
import re

_VAR = re.compile(r"\b([fs])\.([A-Za-z_\u0080-\uffff][\w\u0080-\uffff]*)")
_ALLOWED = (ast.Expression, ast.BoolOp, ast.BinOp, ast.UnaryOp, ast.Compare, ast.Constant,
            ast.Name, ast.Load, ast.And, ast.Or, ast.Not, ast.USub, ast.UAdd, ast.Add, ast.Sub,
            ast.Mult, ast.Div, ast.FloorDiv, ast.Mod, ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE,
            ast.Subscript, ast.Index if hasattr(ast, "Index") else ast.Constant)
_CACHE = {}


class ExprError(ValueError):
    pass


_STR = re.compile(r"(\"(?:[^\"\\]|\\.)*\"|'(?:[^'\\]|\\.)*')")


def _translate_code(s):
    s = s.replace("&&", " and ").replace("||", " or ")
    s = re.sub(r"!(?!=)", " not ", s)
    s = re.sub(r"\btrue\b", "True", s)
    s = re.sub(r"\bfalse\b", "False", s)
    return _VAR.sub(lambda m: 'V["%s.%s"]' % (m.group(1), m.group(2)), s)


def _translate(src):
    parts = _STR.split(str(src))
    # 偶数段是代码，奇数段是字符串字面量（原样保留）
    return "".join(p if i % 2 else _translate_code(p) for i, p in enumerate(parts)).strip()


def compile_expr(src):
    if src in _CACHE:
        return _CACHE[src]
    py = _translate(src)
    try:
        tree = ast.parse(py, mode="eval")
    except SyntaxError as e:
        raise ExprError("表达式语法错误: %r (%s)" % (src, e))
    for node in ast.walk(tree):
        if not isinstance(node, _ALLOWED):
            raise ExprError("表达式含不允许的成分 %s: %r" % (type(node).__name__, src))
        if isinstance(node, ast.Name) and node.id not in ("V", "True", "False"):
            raise ExprError("未知名字 %r（变量要写成 f.x 或 s.x）: %r" % (node.id, src))
    code = compile(tree, "<expr>", "eval")
    _CACHE[src] = code
    return code


class _Vars(dict):
    def __missing__(self, k):
        return 0


def evaluate(src, f, s):
    if src is None or src == "":
        return True
    v = _Vars()
    for k, x in (f or {}).items():
        v["f." + k] = x
    for k, x in (s or {}).items():
        v["s." + k] = x
    try:
        return eval(compile_expr(src), {"__builtins__": {}}, {"V": v})
    except ExprError:
        raise
    except ZeroDivisionError:
        return 0
    except Exception as e:
        raise ExprError("表达式求值失败 %r: %s" % (src, e))


_ASSIGN = re.compile(r"^\s*([fs])\.([\w\u0080-\uffff]+)\s*(\+=|-=|\*=|=)\s*(.+?)\s*$")


def assign(stmts, f, s):
    """执行 'f.x = 1; s.y += 2'。返回改动过的变量名列表。"""
    changed = []
    for st in re.split(r";(?=(?:[^\"']|\"[^\"]*\"|'[^']*')*$)", str(stmts)):
        if not st.strip():
            continue
        m = _ASSIGN.match(st)
        if not m:
            raise ExprError("赋值语句看不懂: %r" % st)
        scope, name, op, rhs = m.groups()
        val = evaluate(rhs, f, s)
        tgt = f if scope == "f" else s
        if op == "=":
            tgt[name] = val
        elif op == "+=":
            tgt[name] = tgt.get(name, 0) + val
        elif op == "-=":
            tgt[name] = tgt.get(name, 0) - val
        elif op == "*=":
            tgt[name] = tgt.get(name, 0) * val
        changed.append(scope + "." + name)
    return changed
