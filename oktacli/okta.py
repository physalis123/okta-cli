import enum
import json
import time
from urllib.parse import urljoin

import requests


class REST(enum.Enum):
    get = "get"
    put = "put"
    post = "post"
    delete = "delete"


class Okta:

    def __init__(self, url, token):
        self.token = token
        self.path_base = "api/v1"
        self.url = url

        self.session = requests.Session()
        self.session.headers.update({
            'Content-Type':  'application/json',
            'Accept':        'application/json',
            'Authorization': 'SSWS ' + token,
        })

    def call_okta_raw(self, path, method, *, params=None, body_obj=None,
                      custom_url=None, custom_path_base=None):
        call_method = getattr(self.session, method.value)
        call_params = {"params": params if params is not None else {}}
        call_url = urljoin(
            (custom_url if custom_url is not None else self.url),
            "/".join(filter(None, (
                custom_path_base.strip("/")
                if custom_path_base is not None
                else self.path_base,
                path.strip("/")
            )))
        )
        if method == REST.post and body_obj:
            call_params["data"] = json.dumps(body_obj)

        while True:
            rsp = call_method(call_url, **call_params)

            if rsp.status_code != 429:
                # not throttled? break the loop.
                break

            # get header with "we're good again" date (epoch time)
            until = int(rsp.headers.get("X-Rate-Limit-Reset"))
            delay = max(1, int(until - time.time()))
            time.sleep(delay)
            # now try again

        if rsp.status_code >= 400:
            raise requests.HTTPError(json.dumps(rsp.json()))
        return rsp

    def call_okta(self, path, method, *,
                  params=None, body_obj=None,
                  result_limit=None,
                  custom_url=None, custom_path_base=None):
        rsp = self.call_okta_raw(path, method, params=params, body_obj=body_obj,
                                 custom_url=custom_url,
                                 custom_path_base=custom_path_base)
        rv = rsp.json()
        # NOW, we either have a SINGLE DICT in the rv variable,
        #     *OR*
        # a list.
        last_url = None
        while True:
            # let's stop if we defined a result_limit
            if result_limit and len(rv) > result_limit:
                break
            # now, let's get all the "next" links. if we do NOT have a list,
            # we do not have "next" links :) . handy!
            url = rsp.links.get("next", {"url": ""})["url"]
            # sanity checks
            if not url or last_url == url:
                break
            last_url = url
            rsp = self.call_okta_raw("", REST.get, custom_url=url, custom_path_base="")
            # now the += operation is safe, cause we have a list.
            # this is a liiiitle bit implicit, but should work smoothly.
            rv += rsp.json()
        # filter out _links items from the final result list
        if isinstance(rv, list):
            for item in rv:
                item.pop("_links", None)
        elif isinstance(rv, dict):
            rv.pop("_links", None)
        return rv

    def list_groups(self, query_ex="", filter_ex=""):
        params = {}
        if query_ex:
            params["query"] = query_ex
        if filter_ex:
            params["filter"] = filter_ex
        return self.call_okta("/groups", REST.get, params=params)

    def list_users(self, filter_query="", search_query=""):
        if filter_query:
            params = {"filter": filter_query}
        elif search_query:
            params = {"search": search_query}
        else:
            params = {}
        params.update({"limit": 1000})
        return self.call_okta("/users", REST.get, params=params)

    def list_apps(self, filter_query="", q_query=""):
        params = {}
        if filter_query:
            params["filter"] = filter_query
        elif q_query:
            params["q"] = q_query
        return self.call_okta("/apps", REST.get, params=params)

    def add_user(self, query_params, body_object):
        return self.call_okta("/users", REST.post,
                              params=query_params,
                              body_obj=body_object)

    def update_user(self, user_id, body_object):
        path = f"/users/{user_id}"
        return self.call_okta(path, REST.post, body_obj=body_object)

    def get_profile_schema(self):
        path = "/meta/schemas/user/default/"
        return self.call_okta(path, REST.get)

    def deactivate_user(self, user_id, send_email=True):
        """
        Deactivates a user.
        :param user_id: The user ID
        :param send_email: On True admins will be notified
        :return: None
        """
        path = "/users/" + user_id + "/lifecycle/deactivate"
        params = {"sendEmail": "true"} if send_email else {}
        return self.call_okta_raw(path, REST.post, params=params)

    def delete_user(self, user_id, send_email=True):
        """
        Deletes a user.
        :param user_id: The user ID
        :param send_email: On True admins will be notified
        :return: None
        """
        path = f"/users/{user_id}"
        params = {"sendEmail": "true"} if send_email else {}
        return self.call_okta_raw(path, REST.delete, params=params)

    def reset_password(self, user_id, *, send_email=True):
        return self.call_okta(
            f"/users/{user_id}/lifecycle/reset_password",
            params={'sendEmail': f"{str(send_email).lower()}"}
        )

    def expire_password(self, user_id, *, temp_password=False):
        return self.call_okta(
            f"/users/{user_id}/lifecycle/expire_password",
            params={'tempPassword': f"{str(temp_password).lower()}"}
        )
