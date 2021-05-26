from typing import Optional

from parsimonious.exceptions import ParseError
from parsimonious.grammar import Grammar, NodeVisitor


class ArithmeticError(Exception):
    pass


class MaxOperatorError(ArithmeticError):
    """ Exceeded the maximum allowed operators """

    pass


class ArithmeticParseError(ArithmeticError):
    """ Encountered an error trying to parse an equation """

    pass


class Operation:
    __slots__ = "operator", "lhs", "rhs"

    def __init__(self, operator, lhs=None, rhs=None):
        self.operator = operator
        self.lhs = lhs
        self.rhs = rhs

    def validate(self):
        if self.operator == "divide" and self.rhs == 0:
            raise ArithmeticError("division by 0 is not allowed")

    def __repr__(self):
        return repr([self.operator, self.lhs, self.rhs])


arithmetic_grammar = Grammar(
    r"""
term                 = maybe_factor remaining_adds
remaining_adds       = add_sub*
add_sub              = add_sub_operator maybe_factor
maybe_factor         = spaces (factor / primary) spaces

factor               = primary remaining_muls
remaining_muls       = mul_div+
mul_div              = mul_div_operator primary

add_sub_operator     = spaces (plus / minus) spaces
mul_div_operator     = spaces (multiply / divide) spaces
# TODO(wmak) allow variables
primary              = spaces (numeric_value / field_value) spaces

# Operator names should match what's in clickhouse
plus                 = "+"
minus                = "-"
multiply             = "*"
divide               = "/"

# TODO(wmak) share these with api/event_search and support decimals
numeric_value        = ~r"[+-]?[0-9]+\.?[0-9]*"
field_value          = ~r"[a-zA-Z_.]+"
spaces               = ~r"\ *"
"""
)


class ArithmeticVisitor(NodeVisitor):
    DEFAULT_MAX_OPERATORS = 10

    # Don't wrap in VisitationErrors
    unwrapped_exceptions = (MaxOperatorError,)

    allowlist = {
        "transaction.duration",
        "spans.http",
        "spans.db",
        "spans.resource",
        "spans.browser",
        "spans.total.time",
    }

    def __init__(self, max_operators):
        super().__init__()
        self.operators = 0
        self.max_operators = max_operators if max_operators else self.DEFAULT_MAX_OPERATORS

    def flatten(self, remaining):
        """ Take all the remaining terms and reduce them to a single tree """
        term = remaining.pop(0)
        while remaining:
            next_term = remaining.pop(0)
            if next_term.lhs is None:
                next_term.lhs = term
            term = next_term
        return term

    def visit_term(self, _, children):
        maybe_factor, remaining_adds = children
        maybe_factor = maybe_factor[0]
        # remaining_adds is either a list containing an Operation, or a Node
        if isinstance(remaining_adds, list):
            # Update the operation with lhs and continue
            remaining_adds[0].lhs = maybe_factor
            return self.flatten(remaining_adds)
        else:
            # if remaining is a node lhs contains a factor so just return that
            return maybe_factor

    def visit_factor(self, _, children):
        primary, remaining_muls = children
        remaining_muls[0].lhs = primary
        return self.flatten(remaining_muls)

    def visited_operator(self):
        """ We visited an operator, increment the count and error if we exceed max """
        self.operators += 1
        if self.operators > self.max_operators:
            raise MaxOperatorError("Exceeded maximum number of operations")

    def visit_add_sub(self, _, children):
        add_sub_operator, maybe_factor = children
        self.visited_operator()
        return Operation(add_sub_operator, rhs=maybe_factor[0])

    def visit_mul_div(self, _, children):
        mul_div_operator, primary = children
        self.visited_operator()
        return Operation(mul_div_operator, rhs=primary)

    @staticmethod
    def strip_spaces(children):
        """ Visitor for a `spaces foo spaces` node """
        _, value, _ = children

        return value

    def visit_maybe_factor(self, _, children):
        return self.strip_spaces(children)

    def visit_primary(self, _, children):
        # Return the 0th element since this is a (numeric/field)
        return self.strip_spaces(children)[0]

    @staticmethod
    def parse_operator(operator):
        # operator is a list since the pattern is (a/b) but we'll only ever want the first value
        return operator[0].expr_name

    def visit_add_sub_operator(self, _, children):
        return self.parse_operator(self.strip_spaces(children))

    def visit_mul_div_operator(self, _, children):
        return self.parse_operator(self.strip_spaces(children))

    def visit_numeric_value(self, node, _):
        return float(node.text)

    def visit_field_value(self, node, _):
        # if not in allowlist error
        field = node.text
        if field not in self.allowlist:
            raise ArithmeticParseError(f"{field} not allowed in arithmetic")
        return field

    def generic_visit(self, node, children):
        return children or node


def parse_arithmetic(equation: str, max_operators: Optional[int] = None) -> Operation:
    """ Given a string equation try to parse it into a set of Operations """
    try:
        tree = arithmetic_grammar.parse(equation)
    except ParseError:
        raise ArithmeticParseError(
            "Unable to parse your equation, make sure it is well formed arithmetic"
        )
    return ArithmeticVisitor(max_operators).visit(tree)


def convert_equation_to_snuba_json(parsed_equation, alias=None):
    """ Convert a parsed equation to the equivalent json for snuba """
    if isinstance(parsed_equation, Operation):
        parsed_equation.validate()
        snuba_json = [
            parsed_equation.operator,
            [
                convert_equation_to_snuba_json(parsed_equation.lhs),
                convert_equation_to_snuba_json(parsed_equation.rhs),
            ],
        ]
        if alias:
            snuba_json.append(alias)
        return convert_equation_to_snuba_json
    else:
        return parsed_equation


def resolve_equation_list(equations, snuba_filter):
    selected_columns = snuba_filter.selected_columns
    for index, equation in enumerate(equations):
        # only supporting 1 operation for now
        parsed_equation = parse_arithmetic(equation, max_operators=2)
        selected_columns.append(
            convert_equation_to_snuba_json(parsed_equation, f"equation[{index}]")
        )
    return {"selected_columns": selected_columns}