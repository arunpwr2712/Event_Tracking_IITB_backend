from fastapi import FastAPI, WebSocket, Depends, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import func
import asyncio
from datetime import datetime, timedelta
import traceback

from database import SessionLocal
from models import Lab, Group, GroupLabAssignment
from ws_manager import ConnectionManager

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "https://event-tracking-iitb-frontend.netlify.app", "*"], # Allows all origins
    allow_credentials=True,
    allow_methods=["*"], # Allows all methods
    allow_headers=["*"], # Allows all headers
)


manager = ConnectionManager()


# def serialize_status(db: Session = None):
#     """Return serializable status containing server time, labs, groups and remaining seconds and allowed labs.

#     If no Session is provided, this function will create and close one for the duration of the call to avoid long-lived sessions
#     that can exhaust connection pools when many concurrent websocket connections are active.
#     """
#     created_local = False
#     if db is None:
#         db = SessionLocal()
#         created_local = True

#     try:
#         now = datetime.utcnow()

#         def _to_iso(dt):
#             return dt.isoformat() + "Z" if dt else None

#         labs = db.query(Lab).all()
#         groups = db.query(Group).all()

#         labs_serialized = [
#             {
#                 "lab_id": lab.lab_id,
#                 "name": lab.name,
#                 "status": lab.status,
#                 "occupied_by": lab.occupied_by,
#             }
#             for lab in labs
#         ]

#         groups_serialized = []
#         for g in groups:
#             remaining = None
#             if g.expected_exit_at:
#                 remaining = max(0, int((g.expected_exit_at - now).total_seconds()))

#             # allowed labs for this group
#             allowed = [r.lab_id for r in db.query(GroupLabAssignment).filter(GroupLabAssignment.group_id == g.group_id).all()]

#             groups_serialized.append({
#                 "group_id": g.group_id,
#                 "volunteer_name": g.volunteer_name,
#                 "state": g.state,
#                 "current_lab": g.current_lab,
#                 "entered_at": _to_iso(g.entered_at),
#                 "expected_exit_at": _to_iso(g.expected_exit_at),
#                 "remaining_seconds": remaining,
#                 "allowed_labs": allowed,
#                 "alarm_8_sent": bool(g.alarm_8_sent),
#                 "alarm_10_sent": bool(g.alarm_10_sent),
#             })

#         return {
#             "type": "STATUS",
#             "server_time": now.isoformat() + "Z",
#             "labs": labs_serialized,
#             "groups": groups_serialized,
#         }
#     finally:
#         if created_local:
#             db.close()

def serialize_status(db: Session = None):
    """
    Return serializable status containing server time, labs, groups and remaining seconds and allowed labs.

    If no Session is provided, this function will create and close one for the duration of the call to avoid long-lived sessions
    that can exhaust connection pools when many concurrent websocket connections are active.
    """
    created_local = False
    if db is None:
        db = SessionLocal()
        created_local = True

    try:
        now = datetime.utcnow()

        def _to_iso(dt):
            return dt.isoformat() + "Z" if dt else None

        # ---- FETCH BASE DATA (NO N+1 QUERIES) ----
        labs = db.query(Lab).all()
        groups = db.query(Group).all()
        assignments = db.query(GroupLabAssignment).all()

        # ---- BUILD LOOKUP MAP ----
        allowed_labs_map = {}
        for a in assignments:
            allowed_labs_map.setdefault(a.group_id, []).append(a.lab_id)

        # ---- SERIALIZE LABS ----
        labs_serialized = [
            {
                "lab_id": lab.lab_id,
                "name": lab.name,
                "status": lab.status,
                "occupied_by": lab.occupied_by,
            }
            for lab in labs
        ]

        # ---- SERIALIZE GROUPS ----
        groups_serialized = []
        for g in groups:
            remaining = None
            if g.expected_exit_at:
                remaining = max(
                    0,
                    int((g.expected_exit_at - now).total_seconds())
                )

            groups_serialized.append({
                "group_id": g.group_id,
                "volunteer_name": g.volunteer_name,
                "state": g.state,
                "current_lab": g.current_lab,
                "entered_at": _to_iso(g.entered_at),
                "expected_exit_at": _to_iso(g.expected_exit_at),
                "remaining_seconds": remaining,
                "allowed_labs": allowed_labs_map.get(g.group_id, []),
                "alarm_8_sent": bool(getattr(g, "alarm_8_sent", False)),
                "alarm_10_sent": bool(getattr(g, "alarm_10_sent", False)),
            })

        return {
            "type": "STATUS",
            "server_time": now.isoformat() + "Z",
            "labs": labs_serialized,
            "groups": groups_serialized,
        }

    finally:
        if created_local:
            db.close()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()




@app.get("/ping")
async def ping():
    return {"status": "ready"}

class RefreshFlag(BaseModel):
    flag: str

@app.post("/refresh")
async def receive_refresh(flag: RefreshFlag):
    # Perform any action you like (e.g., reset session, log, etc.)
    # print(f"Received refresh flag: {flag.flag}")

    return {"status": "ok"}

@app.post("/labs")
async def create_lab(name: str = "", db: Session = Depends(get_db)):
    # find next lab id
    max_id = db.query(func.max(Lab.lab_id)).scalar() or 0
    lab = Lab(lab_id=max_id + 1, name=name or f"Lab {max_id + 1}", status="FREE")
    db.add(lab)
    db.commit()

    # by default do not assign to anyone; caller should assign explicitly
    await manager.broadcast(serialize_status(db))
    return {"lab_id": lab.lab_id}


@app.put("/labs/{lab_id}")
async def update_lab(lab_id: int, name: str, db: Session = Depends(get_db)):
    lab = db.query(Lab).filter(Lab.lab_id == lab_id).first()
    if not lab:
        raise HTTPException(status_code=404, detail="Lab not found")
    lab.name = name
    db.commit()
    # proactively notify clients
    await manager.broadcast(serialize_status(db))
    # return 204 No Content as confirmation
    return Response(status_code=204)


@app.delete("/labs/{lab_id}")
async def delete_lab(lab_id: int, db: Session = Depends(get_db)):
    lab = db.query(Lab).filter(Lab.lab_id == lab_id).first()
    if not lab:
        return JSONResponse(status_code=404, content={"error": "Lab not found"})
    # constraint: cannot delete occupied lab
    if lab.status != "FREE":
        return JSONResponse(status_code=422, content={"error": "Cannot delete occupied lab"})

    # remove assignments
    db.query(GroupLabAssignment).filter(GroupLabAssignment.lab_id == lab_id).delete()
    db.delete(lab)
    db.commit()
    await manager.broadcast(serialize_status(db))
    return JSONResponse(status_code=200, content={"success": True})


@app.post("/groups")
async def create_group(volunteer_name: str = "", db: Session = Depends(get_db)):
    max_id = db.query(func.max(Group.group_id)).scalar() or 0
    g = Group(group_id=max_id + 1, volunteer_name=volunteer_name or f"Volunteer {max_id + 1}", state="WAITING")
    db.add(g)
    db.commit()
    await manager.broadcast(serialize_status(db))
    return {"group_id": g.group_id}


class GroupUpdate(BaseModel):
    volunteer_name: str

# @app.put("/groups/{group_id}")
# async def update_group(group_id: int, volunteer_name: str, db: Session = Depends(get_db)):
#     g = db.query(Group).filter(Group.group_id == group_id).first()
#     if not g:
#         return JSONResponse(status_code=404, content={"error": "Group not found"})
#     g.volunteer_name = volunteer_name
#     db.commit()
#     await manager.broadcast(serialize_status(db))
#     return JSONResponse(status_code=200, content={"success": True})

@app.put("/groups/{group_id}")
async def update_group(
    group_id: int,
    payload: GroupUpdate,
    db: Session = Depends(get_db)
):
    g = db.query(Group).filter(Group.group_id == group_id).first()
    if not g:
        return JSONResponse(status_code=404, content={"error": "Group not found"})

    g.volunteer_name = payload.volunteer_name
    db.commit()

    await manager.broadcast(serialize_status(db))

    return JSONResponse(status_code=200, content={"success": True})

@app.delete("/groups/{group_id}")
async def delete_group(group_id: int, db: Session = Depends(get_db)):
    g = db.query(Group).filter(Group.group_id == group_id).first()
    if not g:
        raise HTTPException(status_code=404, detail="Group not found")
    # constraint: cannot delete a group currently in a lab
    if g.state == "ENTERED":
        raise HTTPException(status_code=422, detail="Cannot delete group currently in a lab")

    # remove assignments
    db.query(GroupLabAssignment).filter(GroupLabAssignment.group_id == group_id).delete()
    db.delete(g)
    db.commit()
    await manager.broadcast(serialize_status(db))
    return {"success": True}


class AssignmentRequest(BaseModel):
    group_id: int
    lab_id: int


@app.post("/assign")
async def assign_lab(req: AssignmentRequest, db: Session = Depends(get_db)):
    group_id = req.group_id
    lab_id = req.lab_id

    g = db.query(Group).filter(Group.group_id == group_id).first()
    lab = db.query(Lab).filter(Lab.lab_id == lab_id).first()
    if not g or not lab:
        return JSONResponse(status_code=404, content={"error": "Group or Lab not found"})

    exists = db.query(GroupLabAssignment).filter(GroupLabAssignment.group_id == group_id, GroupLabAssignment.lab_id == lab_id).first()
    if exists:
        return JSONResponse(status_code=422, content={"error": "Assignment already exists"})

    db.add(GroupLabAssignment(group_id=group_id, lab_id=lab_id))
    db.commit()
    # proactively notify all clients
    await manager.broadcast(serialize_status(db))
    return JSONResponse(status_code=200, content={"success": True})


@app.post("/unassign")
async def unassign_lab(req: AssignmentRequest, db: Session = Depends(get_db)):
    group_id = req.group_id
    lab_id = req.lab_id

    existing = db.query(GroupLabAssignment).filter(GroupLabAssignment.group_id == group_id, GroupLabAssignment.lab_id == lab_id).first()
    if not existing:
        return JSONResponse(status_code=422, content={"error": "Assignment not found"})
    db.query(GroupLabAssignment).filter(GroupLabAssignment.group_id == group_id, GroupLabAssignment.lab_id == lab_id).delete()
    db.commit()
    # proactively notify all clients
    await manager.broadcast(serialize_status(db))
    return JSONResponse(status_code=200, content={"success": True})


@app.get("/assignments")
def get_assignments(group_id: int = None, db: Session = Depends(get_db)):
    q = db.query(GroupLabAssignment)
    if group_id is not None:
        q = q.filter(GroupLabAssignment.group_id == group_id)
    items = q.all()
    return [{"group_id": i.group_id, "lab_id": i.lab_id} for i in items]


@app.post("/enter_lab")
async def enter_lab(group_id: int, lab_id: int, db: Session = Depends(get_db)):
    lab = db.query(Lab).filter(Lab.lab_id == lab_id).first()
    group = db.query(Group).filter(Group.group_id == group_id).first()

    if not lab or not group:
        return JSONResponse(status_code=404, content={"error": "Lab or Group not found"})

    # ensure group is allowed to enter this lab
    allowed = db.query(GroupLabAssignment).filter(GroupLabAssignment.group_id == group_id, GroupLabAssignment.lab_id == lab_id).first()
    if not allowed:
        return JSONResponse(status_code=403, content={"error": "This group is not allowed to enter this lab"})

    if lab.status != "FREE":
        return JSONResponse(status_code=422, content={"error": "Lab occupied"})

    now = datetime.utcnow()

    lab.status = "OCCUPIED"
    lab.occupied_by = group_id

    group.state = "ENTERED"
    group.current_lab = lab_id
    group.entered_at = now
    # timer set to 15 minutes
    group.expected_exit_at = now + timedelta(minutes=15)
    group.alarm_8_sent = 0
    group.alarm_10_sent = 0

    db.commit()

    # send full status so frontend receives correct server time and remaining seconds
    await manager.broadcast(serialize_status(db))
    return JSONResponse(status_code=200, content={"success": True})


@app.post("/exit_lab")
async def exit_lab(group_id: int, db: Session = Depends(get_db)):
    group = db.query(Group).filter(Group.group_id == group_id).first()
    if not group:
        return JSONResponse(status_code=404, content={"error": "Group not found"})
    lab = db.query(Lab).filter(Lab.lab_id == group.current_lab).first()

    if lab:
        lab.status = "FREE"
        lab.occupied_by = None

    group.state = "WAITING"
    group.current_lab = None
    group.entered_at = None
    group.expected_exit_at = None
    group.alarm_8_sent = 0
    group.alarm_10_sent = 0

    db.commit()

    # send full status so frontend receives correct server time and remaining seconds
    await manager.broadcast(serialize_status(db))
    return JSONResponse(status_code=200, content={"success": True})


@app.get("/status")
def status(db: Session = Depends(get_db)):
    # Return the same serialized status used for websocket broadcasts
    return serialize_status(db)


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """Robust websocket handling:
    - Start separate reader and writer tasks so a silent client doesn't cause a tight open/close loop
    - Log disconnect reasons and clean up resources
    """
    import logging
    from fastapi import WebSocketDisconnect

    logger = logging.getLogger(__name__)

    await manager.connect(websocket)

    async def reader():
        # Keep reading to detect client disconnects or messages (if any)
        try:
            while True:
                try:
                    # Wait for a short time for incoming client messages; timeout keeps us responsive
                    msg = await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
                    # currently we don't expect messages from clients; just log if any arrive
                    logger.debug(f"WS received message from {getattr(websocket, 'client', None)}: {msg}")
                except asyncio.TimeoutError:
                    # no message received in this interval, continue to keep connection alive
                    continue
        except WebSocketDisconnect:
            # Normal client disconnect, log and return (no stack trace)
            logger.info(f"WebSocket client disconnected: {getattr(websocket, 'client', None)}")
            return
        except Exception as exc:
            # Any other error - log and return cleanly
            logger.warning(f"WebSocket reader error: {exc}")
            return

    async def writer():
        try:
            # Send an initial status immediately so client sees data at connect
            await websocket.send_json(serialize_status())
            while True:
                await asyncio.sleep(1.0)
                # refresh DB session state each loop to see latest data
                try:
                    status = serialize_status()
                    await websocket.send_json(status)
                except WebSocketDisconnect:
                    # client disconnected while sending; treat as normal and return
                    logger.info(f"WebSocket disconnected during send: {getattr(websocket, 'client', None)}")
                    return
                except Exception as exc:
                    # likely client closed or send failed; log and return
                    logger.info(f"WebSocket send error, closing writer for {getattr(websocket, 'client', None)}: {exc}")
                    return
        except WebSocketDisconnect:
            # Normal disconnect
            logger.info(f"WebSocket disconnected during initial send: {getattr(websocket, 'client', None)}")
            return
        except Exception as exc:
            # unexpected error; log and return
            logger.exception(f"WebSocket writer unexpected error: {exc}")
            return

    # run reader and writer concurrently and stop when either fails
    reader_task = asyncio.create_task(reader())
    writer_task = asyncio.create_task(writer())

    try:
        done, pending = await asyncio.wait({reader_task, writer_task}, return_when=asyncio.FIRST_EXCEPTION)
        for t in pending:
            t.cancel()
        for t in done:
            if t.exception():
                exc = t.exception()
                # handle normal disconnects quietly
                from fastapi import WebSocketDisconnect
                if isinstance(exc, WebSocketDisconnect):
                    logger.info(f"WebSocket closed: {getattr(websocket, 'client', None)} {exc}")
                else:
                    # unexpected exception - log full traceback
                    logger.exception(f"WebSocket endpoint exception: {exc}\n{traceback.format_exc()}")
    except Exception as exc:
        # fallback logging
        logger.exception(f"WebSocket endpoint exception (outer): {exc}\n{traceback.format_exc()}")
    finally:
        # ensure tasks are cleaned
        for t in (reader_task, writer_task):
            if not t.done():
                t.cancel()
        manager.disconnect(websocket)


# Background task to monitor alarms (8 and 10 minutes) and broadcast ALARM messages once
async def alarm_monitor():
    while True:
        await asyncio.sleep(1.0)
        db = SessionLocal()
        try:
            now = datetime.utcnow()
            groups = db.query(Group).filter(Group.state == "ENTERED", Group.expected_exit_at != None).all()
            for g in groups:
                if not g.entered_at:
                    continue
                elapsed = (now - g.entered_at).total_seconds()

                # alarm at 8 minutes elapsed
                if elapsed >= 8 * 60 and not g.alarm_8_sent:
                    g.alarm_8_sent = 1
                    db.commit()
                    try:
                        await manager.broadcast({"type": "ALARM", "group_id": g.group_id, "alarm": "ALARM_8", "message": "8 minute warning"})
                    except Exception:
                        pass

                # alarm at 10 minutes elapsed
                if elapsed >= 10 * 60 and not g.alarm_10_sent:
                    g.alarm_10_sent = 1
                    db.commit()
                    try:
                        await manager.broadcast({"type": "ALARM", "group_id": g.group_id, "alarm": "ALARM_10", "message": "10 minute warning"})
                    except Exception:
                        pass
        finally:
            db.close()


@app.on_event("startup")
def start_background_tasks():
    # start the alarm monitor
    asyncio.create_task(alarm_monitor())


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)


