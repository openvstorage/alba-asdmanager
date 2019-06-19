from ovs_extensions.update.alba_component_update import AlbaComponentUpdater as _albacomponent_updater
from source.tools.system import System


class AlbaComponentUpdater(_albacomponent_updater):
    """
    Implementation of abstract class to update alba
    """

    @classmethod
    def get_node_id(cls):
        # type: () -> str
        """
        Use a factory to return the node id
        :return:
        """
        return System.get_my_machine_id()
