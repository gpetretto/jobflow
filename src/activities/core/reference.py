from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union
from uuid import UUID

from maggma.core import Store
from monty.json import MontyDecoder, MontyEncoder, MSONable


@dataclass
class Reference(MSONable):

    uuid: UUID
    name: str
    attributes: Optional[Tuple[Any]] = tuple()

    def resolve(
        self,
        output_store: Optional[Store] = None,
        output_cache: Optional[Dict[UUID, Dict[str, Any]]] = None,
    ):
        # when resolving multiple references simultaneously it is more efficient
        # to use resolve_references as it will minimize the number of database requests
        if output_store is None and output_cache is None:
            raise ValueError(
                "At least one of output_store and output_cache must be set."
            )

        if output_store and (
            self.uuid not in output_cache or self.name not in output_cache[self.uuid]
        ):
            activity_outputs = output_store.query_one(
                {"uuid": str(self.uuid)}, properties=[self.name]
            )
            output_cache[self.uuid] = activity_outputs

        if self.uuid not in output_cache:
            raise ValueError("Could not resolve reference - uuid not in output_cache")

        if self.name not in output_cache[self.uuid]:
            raise ValueError(
                "Could not resolve reference - field name not in output_cache"
            )

        data = output_cache[self.uuid][self.name]

        for attribute in self.attributes:
            data = getattr(data, attribute)

        return data

    def __getitem__(self, item) -> "Reference":
        return Reference(self.uuid, self.name, self.attributes + (item,))

    def __str__(self):
        if len(self.attributes) > 0:
            attribute_str = ", " + ", ".join(map(str, self.attributes))
        else:
            attribute_str = ""

        return f"Reference({str(self.uuid)}, {self.name}{attribute_str})"

    def __hash__(self):
        return hash(str(self))

    def __eq__(self, other: "Reference") -> bool:
        return (
            self.uuid == other.uuid
            and self.name == other.name
            and self.attributes == other.attributes
        )


def resolve_references(
    references: Sequence[Reference],
    output_store: Optional[Store] = None,
    output_cache: Optional[Dict[UUID, Dict[str, Any]]] = None,
) -> Dict[Reference, Any]:
    from itertools import groupby

    if output_store is None and output_cache is None:
        raise ValueError("At least one of output_store and output_cache must be set.")

    resolved_references = {}
    for uuid, references in groupby(references, key=lambda x: x.uuid):
        if output_store:
            if uuid in output_cache:
                missing_properties = [
                    ref.name for ref in references if ref.name not in output_cache[uuid]
                ]
            else:
                missing_properties = [ref.name for ref in references]

            activity_outputs = output_store.query_one(
                {"uuid": str(uuid)}, properties=missing_properties
            )
            output_cache[uuid] = activity_outputs

        for ref in references:
            resolved_references[ref] = ref.resolve(output_cache=output_cache)

    return resolved_references


def find_reference_locations(arg: Union[Sequence, Dict]) -> Tuple[List[Any, ...], ...]:
    import json

    from activities.core.util import find_key_value

    # serialize the argument to a dictionary
    arg = json.loads(MontyEncoder().encode(arg))

    # recursively find any reference classes
    return find_key_value(arg, "@class", "Reference")


def find_references(arg: Any) -> Tuple[Reference, ...]:
    from pydash import get

    if isinstance(arg, Reference):
        # if the argument is a reference then stop there
        return tuple([arg])

    elif isinstance(arg, (float, int, str, bool)):
        # argument is a primitive, we won't find a reference here
        return tuple()

    locations = find_reference_locations(arg)

    # deserialize references and return
    return tuple([Reference.from_dict(get(arg, loc)) for loc in locations])


def find_and_resolve_references(
    arg: Any,
    output_store: Optional[Store] = None,
    output_cache: Optional[Dict[UUID, Dict[str, Any]]] = None,
) -> Any:
    import json

    from pydash import get, set_

    from activities.core.util import find_key_value

    if isinstance(arg, Reference):
        # if the argument is a reference then stop there
        return arg.resolve(output_store=output_store, output_cache=output_cache)

    elif isinstance(arg, (float, int, str, bool)):
        # argument is a primitive, we won't find a reference here
        return arg

    # serialize the argument to a dictionary
    arg = json.loads(MontyEncoder().encode(arg))

    # recursively find any reference classes
    locations = find_key_value(arg, "@class", "Reference")

    # resolve the references
    references = [Reference.from_dict(get(arg, loc)) for loc in locations]
    resolved_references = resolve_references(references)

    # replace the references in the arg dict
    for location, reference in zip(locations, references):
        resolved_reference = resolved_references[reference]
        set_(arg, location, resolved_reference)

    # deserialize dict array
    return MontyDecoder().decode(json.dumps(arg))
