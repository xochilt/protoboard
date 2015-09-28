#!/usr/bin/env python

from activitytree.models import ActivityTree, UserLearningActivity
from django.utils import timezone
import datetime
from lxml import etree

#Exceptions



class Error(Exception):
    """Base class for exceptions in this module."""
    pass


class TransitionError(Error):
    """Raised when an operation attempts a state transition that's not
    allowed.

    Attributes:
        previous -- state at beginning of transition
        next -- attempted new state
        message -- explanation of why the specific transition is not allowed
    """

    def __init__(self, previous, next, message):
        self.previous = previous
        self.next = next
        self.message = message


class NotAllowed(Error):
    """Raised when an invalid action is encounterd

    Attributes:
        action  -- action to be executed
        message -- explanation of why the specific action is not allowed
    """

    def __init__(self, action, message):
        self.action = action
        self.message = message

    def __str__(self):
        return """%s not allowed, %s""" % (self.action, self.message,)


class SimpleSequencing(object):
    def set_current(self, ula):
        atree = ula.get_atree()

        #If there is a current activity don't do anything
        if atree.current_activity:
            if atree.current_activity == ula:
                return
            else:
                raise NotAllowed('Set Current', "Another activity is already the current activity")

        # Set current activity if everything is fine 
        atree.current_activity = ula
        ula.is_current = True
        ula.last_visited = timezone.now()
        ula.save()
        atree.save()

    def get_current(self, ula):
        atree = ula.get_atree()

        if atree.current_activity:
            return atree.current_activity
        else:
            return None

    def get_path(self,current):
        while current.parent:
            yield current
            current = current.parent
        if not current.parent:
            yield current

    def get_current_path(self, current):
        path = [la for la in self.get_path(current.learning_activity)]
        path.reverse()
        return path



    def exit(self, ula, progress_status=None, objective_status=None, objective_measure=None, kmdynamics=None, attempt=False):

        atree = ActivityTree.objects.get(user=ula.user, root_activity=ula.learning_activity.get_root())

        if not ula.is_current:
            raise NotAllowed('Set Current', "Can only exit a current activity")
            #pass
        else:
            ula.is_current = False
            atree.current_activity = None
            if progress_status:
                ula.progress_status = progress_status
            if objective_status:
                ula.objective_status = objective_status
            if objective_measure is not None:
                ula.objective_measure = objective_measure
            if kmdynamics is not None:
                ula.kmdynamics = kmdynamics
            ula.last_visited = timezone.now()
            if attempt:
                ula.num_attempts += 1
            ula.save()
            atree.save()
            ###
            ### IF rollup_objective = True or rollup_progress = True
            ###
            ula.rollup_rules()

    def update(self, ula, progress_status=None, objective_status=None, objective_measure=None, attempt=False):
        #if not ula.is_current:
        #    raise NotAllowed('Update', "Can only update a current activity")
        #else:
        if progress_status is not None:
            ula.progress_status = progress_status
        if objective_status is not None :
            ula.objective_status = objective_status
        if objective_measure is not None:
            ula.objective_measure = objective_measure
        ula.last_visited = timezone.now()
        if attempt:
            ula.num_attempts += 1
        ula.save()

    def suspend(self, user, activity):
        pass

    def resume(self, user, activity):
        pass

    def assignActivityTree(self, user, activity):
        #Only root activities can be assigned
        if activity.parent is None:
            #If Root bring a List of all child nodes recursive
            nodeList = activity.get_children(recursive=True)
            #Plus root
            nodeList.append(activity)
            #Create another tree of UserLearningActiviy instances
            #All init at default values
            for node in nodeList:
                ula = UserLearningActivity(user=user, learning_activity=node)
                ula.save()
            #Create an instance of ActivityTree
            atree = ActivityTree(user=user, root_activity=activity)
            atree.save()
        else:
            raise NotAllowed('Assign Activity Tree', "Only Root Nodes can be assigned")

    def get_next(self, ula, current):
        if current:
            eroot = get_nav(ula)
            navlist = [e for e in eroot.iter()]
            current_found = False
            for i, item in enumerate(navlist):
                if (item.get("uri") == current.learning_activity.uri) or current_found:
                    current_found = True
                    if i + 1 >= len(navlist):
                        return None
                    next = navlist[i + 1]

                    if next.get("is_container") == "False" and next.get("pre_condition") <> "disabled":
                        return next.get("id")
            return None
        else:
            return None

    def get_prev(self, ula, current):

        if current:
            eroot = get_nav(ula)
            navlist = [e for e in eroot.iter()]
            navlist.reverse()
            current_found = False
            for i, item in enumerate(navlist):
                if (item.get("uri") == current.learning_activity.uri) or current_found:
                    current_found = True
                    if i + 1 >= len(navlist):
                        return None
                    next = navlist[i + 1]

                    if next.get("is_container") == "False" and next.get("pre_condition") <> "disabled":
                        return next.get("id")
            return None
        else:
            return None



import psycopg2
from psycopg2.extras import DictCursor
import datetime
import xml.etree.ElementTree as ET
from django.conf import settings

con = psycopg2.connect(database=settings.DATABASES['default']['NAME'],user=settings.DATABASES['default']['USER'],
                       host=settings.DATABASES['default']['HOST'],port =settings.DATABASES['default']['PORT'], password=settings.DATABASES['default']['PASSWORD'],
                       )

RECORDS = {}

def _get_children(id):
    children = [v for k,v in RECORDS.items() if id == v["parent_id"] ]
    return children

def xml_row(row):
    str_dict = {}
    for k,v in row.items():
        str_dict[k]=unicode(v)
    return str_dict

def sql(root_id,user_id):
    cur = con.cursor(cursor_factory=DictCursor)
    query= """
WITH RECURSIVE nodes_cte AS (
SELECT 	n.id, n.parent_id, n.name, n.id::TEXT AS path,
		n.heading, n.secondary_text, n.description, n.image, n.slug, n.uri, n.lom, n.root_id,
		n.pre_condition_rule, n.post_condition_rule, n.flow, n.forward_only, n.choice,
		n.choice_exit, n.attempt_limit, n.available_from,
		n.available_until, n.is_container, n.is_visible, n.order_in_container
FROM activitytree_learningactivity AS n
WHERE n.parent_id = %s
	UNION ALL
SELECT 	c.id, c.parent_id, c.name, c.id::TEXT AS path,
		c.heading, c.secondary_text, c.description, c.image, c.slug, c.uri, c.lom, c.root_id,
		c.pre_condition_rule, c.post_condition_rule, c.flow, c.forward_only, c.choice,
		c.choice_exit, c.attempt_limit, c.available_from,
		c.available_until, c.is_container, c.is_visible, c.order_in_container
FROM nodes_cte AS p, activitytree_learningactivity AS c
WHERE c.parent_id = p.id
)
(
SELECT  la.id, parent_id, name, ''as path,
		heading, secondary_text, description, image, slug, uri, lom, root_id,
		pre_condition_rule, post_condition_rule, flow, forward_only, choice,
		choice_exit, attempt_limit, available_from,
		available_until, is_container, is_visible, order_in_container,
		pre_condition, recommendation_value, progress_status, objective_status,
        objective_measure, last_visited, num_attempts, is_current

FROM activitytree_learningactivity la, activitytree_userlearningactivity ula

WHERE la.id = %s
	AND la.id = ula.learning_activity_id
	AND ula.user_id = %s

UNION ALL
SELECT  nd.id, parent_id, name,path,
		heading, secondary_text, description, image, slug, uri, lom, root_id,
		pre_condition_rule, post_condition_rule, flow, forward_only, choice,
		choice_exit, attempt_limit, available_from,
		available_until, is_container, is_visible, order_in_container,
		pre_condition, recommendation_value, progress_status, objective_status,
        objective_measure, last_visited, num_attempts, is_current

FROM nodes_cte AS nd, activitytree_userlearningactivity ula
WHERE
	   nd.id = ula.learning_activity_id
	   AND ula.user_id = %s


ORDER BY path ASC

);"""

    cur.execute(query,(root_id,root_id,user_id,user_id))


    recs = cur.fetchall()

    for record in recs:
        RECORDS[record["id"]] = dict(record)


def _get_nav(id,xml_tree=None):
    if RECORDS[id]["parent_id"] is None:
        xml_tree = ET.Element("item")
        xml_tree.attrib = xml_row(RECORDS[id])

    children = _get_children(id)
    children.sort(key=lambda x: x['order_in_container'])
    if children:
        for activity in children:
            exec(activity['pre_condition_rule'])
            if activity['pre_condition'] == 'stopForwardTraversal':
                ET.SubElement(xml_tree,'item',xml_row(activity))
                return xml_tree
            elif activity['pre_condition']  == 'skip':
                pass
            #elif activity['forward_only'] == 'True' and int(activity['num_attempts']) > 0:
            #    activity['pre_condition'] = 'disabled'

            elif activity['num_attempts'] >=  int(activity['attempt_limit']) and int(activity['attempt_limit']) < 100:
                activity['pre_condition'] = 'disabled'



            _get_nav(activity['id'],ET.SubElement(xml_tree,'item',xml_row(activity)))
    else:
        pass
    return xml_tree


def get_attr(uri, attr):
    for k,v in RECORDS.items():
        #print uri,v["uri"],attr,v[attr],RECORDS.items()
        if uri == v["uri"]:
            return v[attr]
    return None




def get_nav(root):
    sql(root.learning_activity.id,root.user_id)
    return _get_nav(root.learning_activity.id)
