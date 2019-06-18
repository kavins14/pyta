import astroid
from astroid.node_classes import NodeNG
from .graph import ControlFlowGraph, CFGBlock
from typing import List, Tuple, Dict, Union


class CFGVisitor:
    """An astroid visitor that creates a control flow graph for a given Python module.

    Private Attributes:
    _control_boundaries: A stack of the boundaries the visitor is currently in.
        The top of the stack corresponds to the end of the list.
        (compound statement [while], {'Break'/'Continue': CFGBlock to link to})
    """
    cfgs: List[ControlFlowGraph]
    _current_cfg: ControlFlowGraph
    _current_block: CFGBlock
    _control_boundaries: List[Tuple[NodeNG, Dict[str, CFGBlock]]]

    def __init__(self) -> None:
        super().__init__()
        self.cfgs = []
        self._current_cfg = None
        self._current_block = None
        self._control_boundaries = []

    def __getattr__(self, attr: str):
        if attr.startswith('visit_'):
            return self.visit_generic
        else:
            raise AttributeError(f"'CFGVisitor' object has not attribute '{attr}'")

    def visit_generic(self, node: NodeNG) -> None:
        """By default, add the expression to the end of the current block."""
        self._current_block.add_statement(node)

    def visit_module(self, module: astroid.Module) -> None:
        self.cfgs.append(ControlFlowGraph())
        self._current_cfg = self.cfgs[0]
        self._current_block = self._current_cfg.start

        for child in module.body:
            child.accept(self)

        self._current_cfg.link_or_merge(self._current_block, self._current_cfg.end)

    def visit_functiondef(self, func: astroid.FunctionDef) -> None:
        previous_cfg = self._current_cfg
        previous_block = self._current_block
        previous_block.add_statement(func)

        self.cfgs.append(ControlFlowGraph())
        self._current_cfg = self.cfgs[-1]

        self._current_block = self._current_cfg.start
        self._current_block.add_statement(func)

        body_block = self._current_cfg.create_block(self._current_block)
        self._current_block = body_block

        for child in func.body:
            child.accept(self)

        self._current_cfg.link_or_merge(self._current_block, self._current_cfg.end)
        self._current_block = previous_block
        self._current_cfg = previous_cfg

    def visit_if(self, node: astroid.If) -> None:
        self._current_block.add_statement(node.test)
        old_curr = self._current_block

        # Handle "then" branch.
        then_block = self._current_cfg.create_block(old_curr)
        self._current_block = then_block
        for child in node.body:
            child.accept(self)
        end_if = self._current_block

        # Handle "else" branch.
        if node.orelse == []:
            end_else = old_curr
        else:
            else_block = self._current_cfg.create_block(old_curr)
            self._current_block = else_block
            for child in node.orelse:
                child.accept(self)
            end_else = self._current_block

        after_if_block = self._current_cfg.create_block()
        self._current_cfg.link_or_merge(end_if, after_if_block)
        self._current_cfg.link_or_merge(end_else, after_if_block)

        self._current_block = after_if_block

    def visit_while(self, node: astroid.While) -> None:
        old_curr = self._current_block

        # Handle "test" block
        test_block = self._current_cfg.create_block()
        test_block.add_statement(node.test)
        self._current_cfg.link_or_merge(old_curr, test_block)

        after_while_block = self._current_cfg.create_block()

        # step into while
        self._control_boundaries.append((node, {astroid.Break.__name__: after_while_block,
                                                astroid.Continue.__name__: test_block}))

        # Handle "body" branch
        body_block = self._current_cfg.create_block(test_block)
        self._current_block = body_block
        for child in node.body:
            child.accept(self)
        end_body = self._current_block
        self._current_cfg.link_or_merge(end_body, test_block)

        # step out of while
        self._control_boundaries.pop()

        # Handle "else" branch
        else_block = self._current_cfg.create_block(test_block)
        self._current_block = else_block
        for child in node.orelse:
            child.accept(self)
        end_else = self._current_block

        self._current_cfg.link_or_merge(end_else, after_while_block)
        self._current_block = after_while_block

    def visit_break(self, node: astroid.Break) -> None:
        self._visit_continue_or_break(node)

    def visit_continue(self, node:astroid.Continue) -> None:
        self._visit_continue_or_break(node)

    def _visit_continue_or_break(self, node: Union[astroid.Break, astroid.Continue]) -> None:
        old_curr = self._current_block
        for boundary, exits in reversed(self._control_boundaries):
            if isinstance(boundary, astroid.While):
                self._current_cfg.link(old_curr, exits[type(node).__name__])
                old_curr.add_statement(node)
                break
        else:
            raise SyntaxError(f'\'{type(node).__name__}\' outside loop')
        unreachable_block = self._current_cfg.create_block()
        self._current_block = unreachable_block

    def visit_return(self, node: astroid.Return) -> None:
        if type(self._current_cfg.start.statements[0]).__name__ != astroid.FunctionDef.__name__:
            raise SyntaxError(f'\'{type(node).__name__}\' outside function')
        old_curr = self._current_block
        self._current_cfg.link(old_curr, self._current_cfg.end)
        old_curr.add_statement(node)
        unreachable_block = self._current_cfg.create_block()
        self._current_block = unreachable_block
